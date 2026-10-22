"""Server start-up and the retry sweep: decay is off and the migration runs
once (decision 14, 2026-10).

The start-up test runs the real server.py as a subprocess in a temp copy of
the app (fake secrets.json, config.json binding loopback only, fixture data),
waits for its start line, stops it, and reads the data files. The sweep test
runs one pass of retry_loop with sleep patched. No network: nothing is queued
for processing, and Ollama being absent only skips the embedding backfill.
Run: python3 -m unittest tests.test_startup
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

TZ = timezone(timedelta(hours=4))
LONG_AGO = (datetime.now(TZ) - timedelta(days=60)).isoformat()
FIXTURE = {"items": [
    {"url": "https://example.org/decayed", "title": "t", "summary": "s", "category": "News",
     "tags": [], "state": "archive", "saved_at": LONG_AGO, "auto_archived_at": LONG_AGO,
     "state_changed_at": LONG_AGO, "state_source": "decay"},
    {"url": "https://example.org/old-untouched", "title": "t", "summary": "s", "category": "News",
     "tags": [], "state": "", "saved_at": LONG_AGO},
]}


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name)
        for name in ("server.py", "extractors.py", "daily_brief.py", "migrations.py"):
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, self.app / name)
        (self.app / "secrets.json").write_text(json.dumps({"auth_token": "t" * 40}))
        (self.app / "config.json").write_text(json.dumps({"bind_addresses": ["127.0.0.1"]}))
        (self.app / "knowledge.json").write_text(json.dumps(FIXTURE, indent=2))
        (self.app / "failures.json").write_text(json.dumps({"items": []}))

    def tearDown(self):
        self.tmp.cleanup()

    def start_and_stop(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.Popen([sys.executable, "-u", "server.py", "0"], cwd=self.app, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines, deadline = [], time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line.rstrip())
                if "starting on" in line:
                    break
        finally:
            proc.terminate()
            proc.wait(timeout=10)
        self.assertTrue(any("starting on" in l for l in lines), "server did not start:\n" + "\n".join(lines))
        return lines

    def items(self):
        return {i["url"]: i for i in json.loads((self.app / "knowledge.json").read_text())["items"]}

    def test_start_restores_and_archives_nothing(self):
        lines = self.start_and_stop()
        items = self.items()
        self.assertEqual(items["https://example.org/old-untouched"]["state"], "",
                         "start-up archived an untouched item (decay is supposed to be off)")
        self.assertEqual(items["https://example.org/decayed"]["state"], "",
                         "start-up did not restore the decay-archived item")
        self.assertIn("restored_at", items["https://example.org/decayed"])
        self.assertTrue(any(l.startswith("[migrate] 2026-10-decay-restore") for l in lines))
        self.assertEqual(len(list(self.app.glob("knowledge.json.pre-migration-*.bak"))), 1)

    def test_second_start_does_not_migrate_again(self):
        self.start_and_stop()
        first = (self.app / "knowledge.json").read_bytes()
        lines = self.start_and_stop()
        self.assertFalse(any(l.startswith("[migrate]") for l in lines), lines)
        self.assertEqual((self.app / "knowledge.json").read_bytes(), first)
        self.assertEqual(len(list(self.app.glob("knowledge.json.pre-migration-*.bak"))), 1)


class StopLoop(BaseException):
    pass


@unittest.skipIf(server is None, "server.py could not be imported here")
class RetrySweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {}
        for name in dir(server):
            value = getattr(server, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(server, name, d / value.name)
        server.DATA_FILE.write_text(json.dumps(FIXTURE))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def test_the_sweep_archives_nothing(self):
        def fake_sleep(seconds):
            if seconds >= 3600:
                raise StopLoop()   # the second wait: one full pass is done
        with mock.patch.object(server.time, "sleep", fake_sleep), \
                mock.patch.object(server, "process_url"):
            with self.assertRaises(StopLoop):
                server.retry_loop()
        items = {i["url"]: i for i in json.loads(server.DATA_FILE.read_text())["items"]}
        self.assertEqual(items["https://example.org/old-untouched"]["state"], "",
                         "the retry sweep archived an untouched item")


if __name__ == "__main__":
    unittest.main()
