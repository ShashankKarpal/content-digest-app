"""Unit tests for the weekly act-rate rollup in daily_brief.py (D6).

Pure functions only: no network, no SMTP, no files outside a temp dir.
Run: python3 -m unittest tests.test_daily_brief_rollup
"""

import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daily_brief as db  # noqa: E402

TZ = timezone(timedelta(hours=4))
NOW = datetime(2026, 9, 7, 7, 0, tzinfo=TZ)  # a Monday


def _item(url, state="", saved_days_ago=30, auto=False, changed_days_ago=None, source=None):
    it = {"url": url, "title": url, "category": "Work", "state": state,
          "saved_at": (NOW - timedelta(days=saved_days_ago)).isoformat()}
    if auto:
        it["auto_archived_at"] = (NOW - timedelta(days=changed_days_ago or 1)).isoformat()
    if changed_days_ago is not None and not auto:
        it["state_changed_at"] = (NOW - timedelta(days=changed_days_ago)).isoformat()
        it["state_source"] = source or "view"
    return it


def _entry(days_ago, to, source, frm=""):
    return {"at": (NOW - timedelta(days=days_ago, hours=1)).isoformat(),
            "url": f"https://example.com/{to}/{days_ago}", "from": frm, "to": to, "source": source}


class RollupWindowTests(unittest.TestCase):
    def test_week_counts_come_from_the_log_not_from_current_state(self):
        items = [_item("https://a", "act", changed_days_ago=20, source="view")]  # old, outside week
        log = [
            _entry(1, "act", "triage-link"),
            _entry(2, "archive", "deck"),
            _entry(3, "revisit", "view"),
            _entry(4, "skip", "deck"),
            _entry(5, "archive", "decay"),
            _entry(6, "", "view"),           # state cleared
            _entry(9, "act", "triage-link"),  # outside the 7-day window
        ]
        r = db.weekly_rollup(items, log, NOW)
        self.assertEqual(r["week"]["act"], 1)
        self.assertEqual(r["week"]["manual_archive"], 1)
        self.assertEqual(r["week"]["revisit"], 1)
        self.assertEqual(r["week"]["deck_skip"], 1)
        self.assertEqual(r["week"]["auto_archived"], 1)
        self.assertEqual(r["week"]["cleared"], 1)
        self.assertEqual(r["week"]["by_source"], {"triage-link": 1, "deck": 2, "view": 2, "decay": 1})

    def test_saves_in_week_counted_from_saved_at(self):
        items = [_item("https://a", saved_days_ago=1), _item("https://b", saved_days_ago=6),
                 _item("https://c", saved_days_ago=8)]
        r = db.weekly_rollup(items, [], NOW)
        self.assertEqual(r["week"]["saves"], 2)

    def test_cumulative_uses_current_item_state(self):
        items = [
            _item("https://1", "act"),
            _item("https://2", "revisit"),
            _item("https://3", "revisit"),
            _item("https://4", "archive", auto=True, changed_days_ago=2),
            _item("https://5", "archive"),           # manual: no auto_archived_at
            _item("https://6", ""),
        ]
        r = db.weekly_rollup(items, [], NOW)
        c = r["cumulative"]
        self.assertEqual(c["total"], 6)
        self.assertEqual(c["act"], 1)
        self.assertEqual(c["revisit"], 2)
        self.assertEqual(c["auto_archived"], 1)
        self.assertEqual(c["manual_archive"], 1)
        self.assertEqual(c["untouched"], 1)

    def test_clean_days_subtract_exclusion_windows(self):
        # Window ending 2026-08-30 covers 08-24..08-30; exclusions hit 08-24 and 08-26..08-28 = 4 days.
        now = datetime(2026, 8, 30, 7, 0, tzinfo=TZ)
        r = db.weekly_rollup([], [], now)
        self.assertEqual(r["week"]["days"], 7)
        self.assertEqual(r["week"]["excluded_days"], 4)
        self.assertEqual(r["week"]["clean_days"], 3)
        r2 = db.weekly_rollup([], [], NOW)  # 09-01..09-07: 08-31 exclusion is outside
        self.assertEqual(r2["week"]["excluded_days"], 0)
        self.assertEqual(r2["week"]["clean_days"], 7)

    def test_since_baseline_clean_days(self):
        r = db.weekly_rollup([], [], NOW)
        # 2026-08-17 .. 2026-09-07 inclusive = 22 days; exclusions inside: 08-17..08-24 (8), 08-26..28 (3), 08-31 (1) = 12
        self.assertEqual(r["since_baseline"]["days"], 22)
        self.assertEqual(r["since_baseline"]["excluded_days"], 12)
        self.assertEqual(r["since_baseline"]["clean_days"], 10)

    def test_malformed_log_lines_are_skipped(self):
        log = [{"at": "not-a-date", "to": "act", "source": "view"}, {"to": "act"}, "garbage"]
        r = db.weekly_rollup([], log, NOW)
        self.assertEqual(r["week"]["act"], 0)


class RowFormatTests(unittest.TestCase):
    def test_row_matches_loopcheck_format(self):
        r = db.weekly_rollup([_item("https://a", "revisit")], [_entry(1, "act", "triage-link")], NOW)
        row = db.format_loopcheck_row(r, NOW)
        self.assertTrue(row.startswith("2026-09-07 | "))
        self.assertEqual(row.count(" | "), 3)
        self.assertIn("act=1", row)
        self.assertIn("revisit=1", row)
        self.assertIn("total=1", row)
        self.assertIn("clean-days=7/7", row)
        self.assertNotIn("\n", row)

    def test_brief_line_is_html_escaped_and_short(self):
        r = db.weekly_rollup([], [], NOW)
        html = db.format_loop_line(r)
        self.assertIn("Loop this week", html)
        self.assertNotIn("<script", html)


class LogAndFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = (db.TRIAGE_LOG_FILE, db.LOOPCHECK_FILE)
        db.TRIAGE_LOG_FILE = self.dir / "triage_log.jsonl"
        db.LOOPCHECK_FILE = self.dir / "loopcheck-history.txt"

    def tearDown(self):
        db.TRIAGE_LOG_FILE, db.LOOPCHECK_FILE = self._old
        self.tmp.cleanup()

    def test_load_triage_log_tolerates_missing_and_bad_lines(self):
        self.assertEqual(db.load_triage_log(), [])
        db.TRIAGE_LOG_FILE.write_text(json.dumps(_entry(1, "act", "view")) + "\n{bad json\n\n")
        entries = db.load_triage_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["to"], "act")

    def test_append_row_once_per_day(self):
        r = db.weekly_rollup([], [], NOW)
        row = db.format_loopcheck_row(r, NOW)
        self.assertTrue(db.append_loopcheck_row(row))
        self.assertFalse(db.append_loopcheck_row(row))  # same date: no duplicate
        lines = db.LOOPCHECK_FILE.read_text().splitlines()
        self.assertEqual(sum(1 for l in lines if l.startswith("2026-09-07 | ")), 1)
        self.assertTrue(lines[0].startswith("#"))  # header written on first create

    def test_append_row_preserves_existing_file(self):
        db.LOOPCHECK_FILE.write_text("# header\n2026-08-17 | baseline | total ~146 | v0.5\n")
        r = db.weekly_rollup([], [], NOW)
        db.append_loopcheck_row(db.format_loopcheck_row(r, NOW))
        lines = db.LOOPCHECK_FILE.read_text().splitlines()
        self.assertEqual(lines[1], "2026-08-17 | baseline | total ~146 | v0.5")
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
