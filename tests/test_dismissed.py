"""Unit tests for persistent deletes (2026-10-06).

A link the owner deletes (a saved item or a failure) must not come back
through the self-healing inbox sweep. Before the fix, _reconcile_inbox
re-queued any authenticated inbox URL that was neither saved nor failed, so a
deleted link with an inbox entry was processed again within one sweep.
Importing server.py runs its module-level setup but starts nothing; the tests
skip cleanly on a machine without the server's dependencies.
Run: python3 -m unittest tests.test_dismissed
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

URL = "https://example.com/post/1"


@unittest.skipIf(server is None, "server.py could not be imported here")
class DismissedLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {k: getattr(server, k) for k in
                       ("INBOX_FILE", "FAILURES_FILE", "DATA_FILE", "DISMISSED_FILE")}
        server.INBOX_FILE = d / "inbox.json"
        server.FAILURES_FILE = d / "failures.json"
        server.DATA_FILE = d / "knowledge.json"
        server.DISMISSED_FILE = d / "dismissed.json"
        server.DATA_FILE.write_text(json.dumps({"items": []}))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))
        self.write_inbox(hours_ago=2)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        self.tmp.cleanup()

    def write_inbox(self, hours_ago):
        at = (datetime.now(server.TZ) - timedelta(hours=hours_ago)).isoformat()
        server.INBOX_FILE.write_text(json.dumps(
            {"items": [{"url": URL, "received_at": at, "authed": True}]}))

    def test_orphan_is_requeued_by_default(self):
        self.assertEqual(server._reconcile_inbox(), [server.normalize_url(URL)])

    def test_deleted_link_is_not_requeued(self):
        server._dismiss(URL)
        self.assertEqual(server._reconcile_inbox(), [])

    def test_recapture_after_the_delete_is_requeued(self):
        three_h_ago = (datetime.now(server.TZ) - timedelta(hours=3)).isoformat()
        server.DISMISSED_FILE.write_text(json.dumps({URL: three_h_ago}))
        # the inbox entry (2 h ago) is newer than the delete (3 h ago)
        self.assertEqual(server._reconcile_inbox(), [server.normalize_url(URL)])

    def test_dismissed_file_is_capped(self):
        old = server.DISMISSED_CAP
        server.DISMISSED_CAP = 3
        try:
            for i in range(5):
                server._dismiss("https://example.com/%d" % i)
            self.assertLessEqual(len(server._load_dismissed()), 3)
        finally:
            server.DISMISSED_CAP = old


if __name__ == "__main__":
    unittest.main()
