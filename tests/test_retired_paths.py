"""Retired POST paths never become saves (red team, 2026-10).

do_POST treats any path without a handler as an add, so removing a handler
would turn a button on an old cached page into a new save of its item URL.
A path listed in RETIRED_POST_PATHS answers 410 "retired" and records nothing:
no inbox entry, no processing. A real server runs on a local ephemeral port;
every data file points into a temp folder and process_url is replaced by a
recorder, so nothing is fetched or summarized.
Run: python3 -m unittest tests.test_retired_paths
"""

import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

TOKEN = "test-token-" + "x" * 32
URL = "https://example.org/an-item"


@unittest.skipIf(server is None, "server.py could not be imported here")
class LiveServerCase(unittest.TestCase):
    """Starts the real Handler on 127.0.0.1 with all data files in a temp dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {}
        for name in dir(server):
            value = getattr(server, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(server, name, d / value.name)
        self._saved["AUTH_TOKEN"] = server.AUTH_TOKEN
        server.AUTH_TOKEN = TOKEN
        server.DATA_FILE.write_text(json.dumps({"items": [
            {"url": URL, "title": "An item", "summary": "s", "category": "Work",
             "tags": [], "state": "", "saved_at": "2026-10-01T09:00:00+04:00"}]}))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))
        self.processed = []
        self._patch = mock.patch.object(server, "process_url",
                                        side_effect=lambda *a, **k: self.processed.append(a))
        self._patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._patch.stop()
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request("POST", path, json.dumps(body), {
            "Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        time.sleep(0.2)  # let any thread the handler started run
        return resp.status, json.loads(data or b"{}")

    def inbox_urls(self):
        if not server.INBOX_FILE.exists():
            return []
        return [e["url"] for e in json.loads(server.INBOX_FILE.read_text())["items"]]


class RetiredPathTests(LiveServerCase):
    def test_a_retired_path_answers_retired_and_saves_nothing(self):
        # create=True so the same test runs against code that predates the
        # list: there the path falls through to the add path (the control).
        with mock.patch.object(server, "RETIRED_POST_PATHS", frozenset({"/old-button"}), create=True):
            status, body = self.post("/old-button", {"url": URL, "state": "act"})
        self.assertEqual(self.processed, [], "a retired path started a save")
        self.assertEqual(self.inbox_urls(), [], "a retired path wrote an inbox entry")
        self.assertEqual(status, 410)
        self.assertEqual(body.get("status"), "retired")

    def test_add_still_ingests(self):
        status, _ = self.post("/add", {"url": "https://example.org/new"})
        self.assertEqual(status, 200)
        self.assertEqual(self.inbox_urls(), ["https://example.org/new"])
        self.assertEqual(self.processed, [("https://example.org/new",)])


def item_state():
    return json.loads(server.DATA_FILE.read_text())["items"][0]["state"]


class RetiredTriageTests(LiveServerCase):
    """Decision 14: the card buttons, the deck and the emailed links are gone."""

    def test_state_and_deck_skip_are_retired(self):
        for path, body in (("/state", {"url": URL, "state": "act", "source": "view"}),
                           ("/deck/skip", {"url": URL})):
            status, answer = self.post(path, body)
            self.assertEqual(self.processed, [], path)
            self.assertEqual(self.inbox_urls(), [], path)
            self.assertEqual((status, answer.get("status")), (410, "retired"), path)
        self.assertEqual(item_state(), "")
        self.assertFalse((Path(self.tmp.name) / "resurface.json").exists(), "the fatigue ledger was written")

    def test_a_query_string_or_trailing_slash_does_not_dodge_the_retired_list(self):
        for path in ("/state?x=1", "/state/", "/deck/skip/", "/deck/skip?a=b"):
            status, answer = self.post(path, {"url": URL, "state": "archive"})
            self.assertEqual(self.processed, [], f"{path} started a save")
            self.assertEqual(self.inbox_urls(), [], f"{path} wrote an inbox entry")
            self.assertEqual((status, answer.get("status")), (410, "retired"), path)

    def test_an_old_emailed_triage_link_says_retired_and_changes_nothing(self):
        import hmac
        import urllib.parse
        expires = int(time.time()) + 3600
        msg = f"{URL}|act|{expires}".encode()   # the pre-decision-14 signing scheme
        sig = hmac.new(TOKEN.encode(), b"triage-v1:" + msg, "sha256").hexdigest()
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request("GET", f"/triage?u={urllib.parse.quote(URL, safe='')}&s=act&e={expires}&sig={sig}")
        resp = conn.getresponse()
        page = resp.read().decode()
        conn.close()
        self.assertEqual(item_state(), "", "an old triage link still changed the item")
        self.assertEqual(resp.status, 200)
        self.assertIn("retired", page)

    def test_the_knowledge_base_page_has_no_triage_controls(self):
        page = server.build_html(json.loads(server.DATA_FILE.read_text())["items"], failures=[])
        for gone in ("setState(", "openDeck(", "review-btn", "state-select", '"/state"', "/deck/skip"):
            self.assertNotIn(gone, page)
        self.assertIn("dismissItem(", page)   # delete stays
        self.assertIn("ask-btn", page)        # Ask stays


if __name__ == "__main__":
    unittest.main()
