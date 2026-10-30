"""A POST with a negative, malformed or missing Content-Length is refused
before the body is read (leak audit M4, 2026-10).

int("-1") passed the size cap, and rfile.read(-1) then waited for the client
to hang up, before or without the token: one connection could hold a server
thread for as long as it liked. Requests go over a raw socket, because
http.client always writes a correct Content-Length. The daily capture-path
check sends an empty POST /add with no token (no Content-Length at all) and
expects 401; that stays true, and is checked with curl itself when present.
Run: python3 -m unittest tests.test_content_length
"""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
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


@unittest.skipIf(server is None, "server.py could not be imported here")
class ContentLengthTests(unittest.TestCase):
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
        self._patch = mock.patch.object(server, "process_url", lambda *a, **k: None)
        self._patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._patch.stop()
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def status(self, length_header, token=False):
        """Send headers only and keep the socket open: a server that waits
        for the body never answers within the timeout."""
        lines = ["POST /add HTTP/1.1", f"Host: 127.0.0.1:{self.port}"]
        if token:
            lines.append("Authorization: Bearer " + TOKEN)
        if length_header is not None:
            lines.append("Content-Length: " + length_header)
        s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        try:
            s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            try:
                first = s.recv(200).decode(errors="replace").split("\r\n", 1)[0]
            except socket.timeout:
                return "no answer: the server is waiting for a body"
        finally:
            s.close()
        return first.split(" ")[1] if first.startswith("HTTP/") else first

    def test_a_negative_length_is_refused_without_the_token(self):
        self.assertEqual(self.status("-1"), "400")

    def test_a_negative_length_is_refused_with_the_token(self):
        self.assertEqual(self.status("-1", token=True), "400")

    def test_a_malformed_length_is_refused(self):
        self.assertEqual(self.status("12abc", token=True), "400")
        self.assertEqual(self.status("", token=True), "400")

    def test_a_missing_length_with_the_token_is_refused(self):
        self.assertEqual(self.status(None, token=True), "411")

    def test_a_missing_length_without_the_token_is_still_401(self):
        self.assertEqual(self.status(None), "401")

    def test_a_good_length_still_works(self):
        self.assertEqual(self.status("0", token=True), "200")

    @unittest.skipIf(shutil.which("curl") is None, "curl is not installed here")
    def test_the_daily_capture_path_probe_still_gets_401(self):
        # The exact command the 09:15 check runs, pointed at this test server.
        out = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-m", "8", "-w", "%{http_code}", "-X", "POST",
             f"http://127.0.0.1:{self.port}/add"],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(out.stdout, "401")


if __name__ == "__main__":
    unittest.main()
