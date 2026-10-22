"""Every page fetch checks the first URL and each redirect with the SSRF
guard (review, 2026-10).

Plain urlopen followed up to 10 redirects unchecked, so a public URL, or a
short link the resolver had refused, could bounce the server into its own
network; normalize_url could fetch a lookalike reddit host before any check.
A real local server plays both a public site and an inside address. Fake DNS
answers the guard's question (where does this name point?) with a public
address for site.invalid and loopback for every other name, while every
connection goes to the local server; connection attempts are recorded,
because the attempt itself is the leak.
Run: python3 -m unittest tests.test_redirect_guard
"""

import json
import socket
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extractors  # noqa: E402

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

REAL_GETADDRINFO = socket.getaddrinfo


class InsideRedirectCase(unittest.TestCase):
    def setUp(self):
        self.hits = []
        hits = self.hits

        class Site(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", f"http://inside.invalid:{self.server.server_address[1]}/secret")
                    self.end_headers()
                    return
                body = ("secret admin page " * 50).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]
        self.start_url = f"http://site.invalid:{self.port}/start"
        self.connections = []
        connections = self.connections

        def split_dns(host, port, *args, **kwargs):
            if port is None:   # the guard asking where a name points
                return REAL_GETADDRINFO("93.184.216.34" if host == "site.invalid" else "127.0.0.1",
                                        port, *args, **kwargs)
            connections.append(host)   # a connection attempt: always the local server
            return REAL_GETADDRINFO("127.0.0.1", port, *args, **kwargs)
        self._dns = mock.patch.object(socket, "getaddrinfo", split_dns)
        self._dns.start()

    def tearDown(self):
        self._dns.stop()
        self.httpd.shutdown()
        self.httpd.server_close()


class GuardedFetchTests(InsideRedirectCase):
    def test_an_extractor_fetch_never_follows_a_redirect_inside(self):
        try:
            extractors._get(self.start_url, timeout=5)
        except Exception:
            pass
        self.assertEqual(self.hits.count("/start"), 1)
        self.assertNotIn("/secret", self.hits, "an extractor fetch followed a redirect into the network")

    def test_a_first_url_that_points_inside_is_never_requested(self):
        try:
            extractors._get(f"http://inside.invalid:{self.port}/secret", timeout=5)
        except Exception:
            pass
        self.assertEqual(self.connections, [], "a fetch connected to an address inside the network")
        self.assertEqual(self.hits, [])

    def test_a_lookalike_reddit_host_is_not_fetched_while_normalizing(self):
        extractors.normalize_url("http://xreddit.com/a")
        self.assertEqual(self.connections, [], "normalize_url fetched a host that points inside")

    @unittest.skipIf(server is None, "server.py could not be imported here")
    def test_a_page_fetch_never_follows_a_redirect_inside(self):
        fake = types.ModuleType("trafilatura")
        fake.extract = lambda html, **kwargs: html
        with mock.patch.dict(sys.modules, {"trafilatura": fake}):
            text = server.fetch_url_content(self.start_url)
        self.assertNotIn("/secret", self.hits, "the page fetch followed a redirect into the network")
        self.assertFalse(text and "secret admin page" in text)


@unittest.skipIf(server is None, "server.py could not be imported here")
class UnresolvedShortLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {}
        for name in dir(server):
            value = getattr(server, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(server, name, d / value.name)
        server.DATA_FILE.write_text(json.dumps({"items": []}))
        server.FAILURES_FILE.write_text(json.dumps({"items": []}))

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def test_a_short_link_the_resolver_refused_is_never_fetched(self):
        fetched = []
        with mock.patch.object(socket, "getaddrinfo",
                               lambda h, *a, **k: REAL_GETADDRINFO("93.184.216.34", *a, **k)), \
                mock.patch.object(extractors, "_resolve_short_link", lambda url: None), \
                mock.patch.object(server, "fetch_url_content", side_effect=lambda url: fetched.append(url)):
            result = server.process_url("https://bit.ly/abc123")
        self.assertEqual(fetched, [], "an unresolved short link was handed to the page fetch")
        self.assertEqual(result["status"], "failed")
        failures = json.loads(server.FAILURES_FILE.read_text())["items"]
        self.assertEqual([(f["url"], f["error_type"]) for f in failures], [("https://bit.ly/abc123", "fetch")])


if __name__ == "__main__":
    unittest.main()
