"""The token never signs in from a URL (leak audit H3, 2026-10).

GET /view?token=... used to set the session cookie, so the token sat in
browser history and, with history sync on, in the Google account. Now the
Locked form posts the token, POST /view sets the cookie, and an old link with
the token in it gets the sign-in page and no cookie. A real server runs on a
local ephemeral port; every data file points into a temp folder.
Run: python3 -m unittest tests.test_view_sign_in
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

TOKEN = "test-token-" + "x" * 32


@unittest.skipIf(server is None, "server.py could not be imported here")
class ViewSignInTests(unittest.TestCase):
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
        server.DATA_FILE.write_text(json.dumps({"items": []}))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.request(method, path, body, headers or {})
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp, data

    def post_form(self, token):
        return self.request("POST", "/view", urllib.parse.urlencode({"token": token}),
                            {"Content-Type": "application/x-www-form-urlencoded"})

    def test_an_old_link_with_the_right_token_does_not_sign_in(self):
        resp, page = self.request("GET", "/view?token=" + urllib.parse.quote(TOKEN))
        self.assertEqual(resp.status, 401)
        self.assertIsNone(resp.getheader("Set-Cookie"), "a token in the URL set the session cookie")
        self.assertIn("Please sign in", page)
        self.assertNotIn(TOKEN, page)

    def test_a_signed_in_browser_is_sent_off_an_old_link(self):
        cookie = f"{server.COOKIE_NAME}={server._session_cookie_value()}"
        resp, _ = self.request("GET", "/view?token=" + urllib.parse.quote(TOKEN), headers={"Cookie": cookie})
        self.assertEqual(resp.status, 303, "a signed-in browser kept the token-bearing URL")
        self.assertEqual(resp.getheader("Location"), "/view")

    def test_an_out_of_date_cookie_is_named(self):
        # Review round 2: after a token change, a cookie the extension set from
        # an old token used to give a bare Locked page.
        resp, page = self.request("GET", "/view", headers={"Cookie": f"other=1; {server.COOKIE_NAME}=stale"})
        self.assertEqual(resp.status, 401)
        self.assertIn("out of date", page)
        self.assertIn("extension", page)

    def test_no_token_on_the_server_is_not_blamed_on_the_browser(self):
        # Review round 3: with a placeholder token every cookie fails, and the
        # browser's sign-in is not the fault.
        server.AUTH_TOKEN = ""
        resp, page = self.request("GET", "/view", headers={"Cookie": f"{server.COOKIE_NAME}=anything"})
        self.assertEqual(resp.status, 401)
        self.assertNotIn("out of date", page)

    def test_a_good_cookie_beside_an_old_one_still_signs_in(self):
        good = f"{server.COOKIE_NAME}={server._session_cookie_value()}"
        resp, _ = self.request("GET", "/view", headers={"Cookie": f"{server.COOKIE_NAME}=old; {good}"})
        self.assertEqual(resp.status, 200)

    def test_the_locked_form_posts_the_token(self):
        resp, page = self.request("GET", "/view")
        self.assertEqual(resp.status, 401)
        self.assertIn('method="POST" action="/view"', page)
        self.assertNotIn('method="GET"', page)
        self.assertNotIn("Please sign in", page, "a plain visit is not told about old links")

    def test_posting_the_right_token_signs_in(self):
        resp, _ = self.post_form(TOKEN)
        self.assertEqual(resp.status, 303)
        self.assertEqual(resp.getheader("Location"), "/view")
        cookie = resp.getheader("Set-Cookie") or ""
        self.assertTrue(cookie.startswith(f"{server.COOKIE_NAME}={server._session_cookie_value()};"), cookie)
        self.assertIn("HttpOnly", cookie)
        resp, page = self.request("GET", "/view", headers={"Cookie": cookie.split(";", 1)[0]})
        self.assertEqual(resp.status, 200)
        self.assertNotIn("Locked", page)

    def test_posting_a_wrong_token_does_not_sign_in(self):
        resp, page = self.post_form("wrong-" + TOKEN)
        self.assertEqual(resp.status, 401)
        self.assertIsNone(resp.getheader("Set-Cookie"))
        self.assertIn("not accepted", page)

    def test_a_sign_in_post_is_never_recorded_as_a_capture(self):
        self.post_form(TOKEN)
        self.assertFalse(server.INBOX_FILE.exists(), "the sign-in post wrote the capture inbox")

    def test_the_cookie_value_matches_the_extension(self):
        # tests/extension_acceptance.test.js pins the popup's value for the
        # same token; the two sides must derive the same cookie.
        server.AUTH_TOKEN = "test-token"
        self.assertEqual(server._session_cookie_value(),
                         "4c98a261ffb59d2fb844723e5a40c3f2be729f554dce4a3badbc08d507e3e5d5")


if __name__ == "__main__":
    unittest.main()
