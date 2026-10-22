"""/health says when the morning brief was last sent (2026-10).

daily_brief.py stamps brief_sent.json only after SMTP accepted the message;
server.py reports the stamp as last_brief_sent_at. A check outside the app
can then tell a brief that stopped from a quiet day. No SMTP, no network.
Run: python3 -m unittest tests.test_brief_stamp
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daily_brief as db  # noqa: E402

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

TZ = timezone(timedelta(hours=4))


class BriefStampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._saved = {}
        for name in dir(db):
            value = getattr(db, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(db, name, self.dir / value.name)
        now = datetime.now(TZ)
        db.KNOWLEDGE_FILE.write_text(json.dumps({"items": [
            {"url": "https://a.dev/1", "title": "One", "category": "Work", "summary": "s", "state": "",
             "saved_at": (now - timedelta(hours=1)).isoformat()}]}))
        db.CONFIG_FILE.write_text(json.dumps({"smtp_user": "u", "smtp_password": "p", "recipient": "r"}))
        self.stamp = self.dir / "brief_sent.json"

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(db, name, value)
        self.tmp.cleanup()

    def run_main(self, *args, send=lambda c, s, b: None):
        with mock.patch.object(db, "send_email", side_effect=send), \
                mock.patch.object(sys, "argv", ["daily_brief.py", *args]):
            return db.main()

    def test_a_sent_brief_is_stamped(self):
        self.assertEqual(self.run_main(), 0)
        self.assertTrue(self.stamp.exists(), "no brief_sent.json after a sent brief")
        stamp = json.loads(self.stamp.read_text())
        self.assertEqual(stamp["items"], 1)
        self.assertLess(abs((datetime.fromisoformat(stamp["at"]) - datetime.now(TZ)).total_seconds()), 60)

    def test_a_dry_run_is_not_stamped(self):
        self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertFalse(self.stamp.exists())

    def test_a_failed_send_is_not_stamped(self):
        def refuse(config, subject, body):
            raise OSError("SMTP down")
        self.assertEqual(self.run_main(send=refuse), 1)
        self.assertFalse(self.stamp.exists())


@unittest.skipIf(server is None, "server.py could not be imported here")
class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {}
        for name in dir(server):
            value = getattr(server, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(server, name, d / value.name)
        self.stamp = d / "brief_sent.json"

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def health(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            conn.request("GET", "/health")
            body = json.loads(conn.getresponse().read())
            conn.close()
            return body
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_health_reports_the_last_sent_brief(self):
        self.stamp.write_text(json.dumps({"at": "2026-10-23T07:00:41+04:00", "items": 3}))
        self.assertEqual(self.health().get("last_brief_sent_at"), "2026-10-23T07:00:41+04:00")

    def test_health_says_none_before_any_brief_and_on_a_bad_file(self):
        body = self.health()
        self.assertIn("last_brief_sent_at", body)
        self.assertIsNone(body["last_brief_sent_at"])
        self.stamp.write_text("{broken")
        self.assertIsNone(self.health()["last_brief_sent_at"])


if __name__ == "__main__":
    unittest.main()
