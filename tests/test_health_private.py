"""/health tells a stranger only that the server answers (leak audit M4, 2026-10).

Without the token, /health used to report each device's last contact, the
last save and the start time, so a week of polling showed when the owner
wakes and which device they use. Now an unauthenticated poll gets a minimal
200 (the Mac client's watchdog and the extension's Test connection still
work), the full snapshot needs the token, and no health poll counts as client
contact. The Mac client sends its token so its menu still shows the last
capture contact. A real server runs on a local ephemeral port; every data
file points into a temp folder.
Run: python3 -m unittest tests.test_health_private
"""

import http.client
import json
import sys
import tempfile
import threading
import types
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
PRIVATE_KEYS = {"started_at", "last_save_at", "last_client_contact_at", "clients", "processing",
                "failures", "last_brief_sent_at"}


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
        self._saved["AUTH_TOKEN"] = server.AUTH_TOKEN
        server.AUTH_TOKEN = TOKEN
        server.DATA_FILE.write_text(json.dumps({"items": [
            {"url": "https://example.org/a", "title": "A", "summary": "s", "category": "Work",
             "tags": [], "saved_at": "2026-10-29T07:12:00+04:00"}]}))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))
        server.CLIENTS_FILE.write_text(json.dumps({"shortcut": "2026-10-30T06:31:00+04:00"}))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def health(self, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request("GET", "/health", headers=headers or {})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        self.cache_control = resp.getheader("Cache-Control")
        return resp.status, body

    def test_the_full_snapshot_is_never_cached(self):
        self.health({"Authorization": "Bearer " + TOKEN})
        self.assertEqual(self.cache_control, "no-store")

    def test_an_unauthenticated_poll_gets_a_minimal_200(self):
        status, body = self.health()
        self.assertEqual(status, 200)
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body.get("version"), server.SERVER_VERSION)
        self.assertEqual(PRIVATE_KEYS & set(body), set(), "an unauthenticated /health shows routine fields")
        self.assertNotIn("06:31", json.dumps(body))
        self.assertNotIn("07:12", json.dumps(body))

    def test_a_wrong_token_gets_the_minimal_body_too(self):
        _, body = self.health({"Authorization": "Bearer wrong"})
        self.assertEqual(PRIVATE_KEYS & set(body), set())

    def test_the_token_gets_the_full_snapshot(self):
        status, body = self.health({"Authorization": "Bearer " + TOKEN})
        self.assertEqual(status, 200)
        self.assertEqual(body["last_save_at"], "2026-10-29T07:12:00+04:00")
        self.assertEqual(body["clients"], {"shortcut": "2026-10-30T06:31:00+04:00"})

    def test_a_health_poll_never_counts_as_contact(self):
        self.health({"Authorization": "Bearer " + TOKEN, "X-Client": "mac-client"})
        self.health()
        self.assertEqual(json.loads(server.CLIENTS_FILE.read_text()),
                         {"shortcut": "2026-10-30T06:31:00+04:00"})


class MacClientProbeTests(unittest.TestCase):
    def test_the_mac_client_sends_its_token_to_health(self):
        self.assertEqual(self.probe_auth(), "Bearer " + TOKEN)

    def test_the_mac_client_never_sends_its_token_elsewhere(self):
        # CD_HEALTH_URL exists to point the watchdog at a test port or host.
        self.assertIsNone(self.probe_auth("http://elsewhere.test/health"))

    def probe_auth(self, health_url=None):
        """Run the client's probe; return the Authorization header it sent."""
        # client.py needs rumps (a menu bar library) only for its UI; a stand-in
        # module is enough to import it and call the probe.
        fake_rumps = types.ModuleType("rumps")
        fake_rumps.App = type("App", (), {})
        with mock.patch.dict(sys.modules, {"rumps": fake_rumps}):
            sys.modules.pop("client", None)
            import client
            seen = []

            class Reply:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"ok": true}'

            with mock.patch.object(client, "AUTH_TOKEN", TOKEN), \
                    mock.patch.object(client, "HEALTH_URL", health_url or client.SERVER + "/health"), \
                    mock.patch.object(client.urllib.request, "urlopen",
                                      lambda req, timeout: seen.append(req) or Reply()):
                ok, _ = client.ContentDigestClient._probe(None)
            sys.modules.pop("client", None)
        self.assertTrue(ok)
        return seen[0].get_header("Authorization")


if __name__ == "__main__":
    unittest.main()
