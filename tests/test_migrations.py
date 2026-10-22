"""Unit tests for the one-time data migrations (migrations.py, 2026-10).

Pure file work in a temp folder: no network, no server.
Run: python3 -m unittest tests.test_migrations
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import migrations  # noqa: E402

TZ = timezone(timedelta(hours=4))
NOW = datetime(2026, 10, 22, 14, 0, tzinfo=TZ)
OLD = "2026-09-20T07:00:00+04:00"


def item(url, **fields):
    base = {"url": url, "title": url, "summary": "s", "category": "Work", "tags": [],
            "state": "", "saved_at": "2026-08-01T09:00:00+04:00"}
    base.update(fields)
    return base


FIXTURE = [
    item("https://a/decay-new", state="archive", auto_archived_at=OLD,
         state_changed_at=OLD, state_source="decay"),
    item("https://b/decay-old", state="archive", auto_archived_at=OLD),   # before 2026-09-05: no state_source
    item("https://c/hand", state="archive", state_changed_at=OLD, state_source="view"),
    item("https://d/hand-after-decay", state="archive", auto_archived_at="2026-08-30T07:00:00+04:00",
         state_changed_at=OLD, state_source="deck"),
    item("https://e/later", state="revisit"),
    item("https://f/neutral"),
]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.data = self.dir / "knowledge.json"
        self.data.write_text(json.dumps({"items": FIXTURE}, indent=2))
        (self.dir / "failures.json").write_text(json.dumps({"items": [{"url": "https://x"}]}))
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_once(self, now=NOW):
        return migrations.run(self.dir, now=now, log=self.lines.append)

    def items(self):
        return {i["url"]: i for i in json.loads(self.data.read_text())["items"]}

    def test_decay_archives_are_restored_with_history(self):
        result = self.run_once()["2026-10-decay-restore"]
        items = self.items()
        for url in ("https://a/decay-new", "https://b/decay-old"):
            it = items[url]
            self.assertEqual(it["state"], "")
            self.assertEqual(it["restored_at"], NOW.isoformat())
            self.assertEqual(it["state_history"][-1]["state"], "archive")
            self.assertEqual(it["state_history"][-1]["auto_archived_at"], OLD)
            self.assertEqual(it["auto_archived_at"], OLD)   # old fields stay: no data deleted
        self.assertEqual(items["https://b/decay-old"]["state_history"][-1]["source"], "decay")
        self.assertEqual(result["restored"], 2)
        self.assertEqual(result["decay_archived_before"], 2)

    def test_hand_archives_and_other_states_are_untouched(self):
        before = {i["url"]: dict(i) for i in FIXTURE}
        result = self.run_once()["2026-10-decay-restore"]
        items = self.items()
        for url in ("https://c/hand", "https://d/hand-after-decay", "https://e/later", "https://f/neutral"):
            self.assertEqual(items[url], before[url])
        self.assertEqual(result["manual_archive_before"], 2)
        self.assertEqual(result["manual_archive_after"], 2)
        self.assertEqual(result["archived_after"], 2)

    def test_backups_are_byte_identical_and_ignored_by_git(self):
        original = self.data.read_bytes()
        self.run_once()
        stamp = NOW.strftime("%Y%m%d-%H%M%S")
        k = self.dir / f"knowledge.json.pre-migration-{stamp}.bak"
        f = self.dir / f"failures.json.pre-migration-{stamp}.bak"
        self.assertEqual(k.read_bytes(), original)
        self.assertTrue(f.exists())
        marker = json.loads((self.dir / "migrations.json").read_text())
        self.assertEqual(marker["applied"]["2026-10-decay-restore"]["backups"], [k.name, f.name])
        self.assertTrue(k.name.endswith(".bak"))   # the repo's *.bak rule keeps it out of git

    def test_second_start_does_nothing(self):
        self.run_once()
        after_first = self.data.read_bytes()
        backups = sorted(p.name for p in self.dir.glob("*.bak"))
        self.assertEqual(self.run_once(now=NOW + timedelta(minutes=5)), {})
        self.assertEqual(self.data.read_bytes(), after_first)
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.bak")), backups)

    def test_idempotent_by_content_without_the_marker(self):
        self.run_once()
        (self.dir / "migrations.json").unlink()
        result = self.run_once(now=NOW + timedelta(minutes=5))["2026-10-decay-restore"]
        self.assertEqual(result["restored"], 0)
        self.assertEqual(len(self.items()["https://a/decay-new"]["state_history"]), 1)

    def test_unreadable_marker_leaves_data_untouched(self):
        (self.dir / "migrations.json").write_text("{not json")
        before = self.data.read_bytes()
        self.assertEqual(self.run_once(), {})
        self.assertEqual(self.data.read_bytes(), before)
        self.assertEqual(list(self.dir.glob("*.bak")), [])

    def test_a_failing_migration_writes_nothing_and_no_marker(self):
        def boom(items, now):
            raise RuntimeError("bad data")
        before = self.data.read_bytes()
        with mock.patch.object(migrations, "MIGRATIONS", (("2026-10-boom", boom),)):
            self.assertEqual(self.run_once(), {})
        self.assertEqual(self.data.read_bytes(), before)
        self.assertFalse((self.dir / "migrations.json").exists())
        self.assertTrue(any("FAILED" in line for line in self.lines))

    def test_a_malformed_knowledge_file_makes_no_backups_however_often_it_starts(self):
        self.data.write_text("{half a file")
        for minute in range(3):
            self.assertEqual(self.run_once(now=NOW + timedelta(minutes=minute)), {})
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.bak")), [], "each start left a backup pair")
        self.assertEqual(self.data.read_text(), "{half a file")
        self.assertFalse((self.dir / "migrations.json").exists())
        self.assertTrue(any("unreadable" in line for line in self.lines))

    def test_fresh_install_is_recorded_as_done(self):
        self.data.unlink()
        self.assertEqual(self.run_once(), {})
        marker = json.loads((self.dir / "migrations.json").read_text())
        self.assertIn("2026-10-decay-restore", marker["applied"])
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
