"""Capture fixes (decision 14, 2026-10): short links resolved hop by hop
through the SSRF guard, artifact_urls on new saves, feed pages flagged.

No real network. DNS is answered by a fake getaddrinfo, single hops are
answered by a fake _fetch_hop, and the one end-to-end resolver test uses a
real HTTP server on 127.0.0.1 that records every request it receives.
Run: python3 -m unittest tests.test_capture_links
"""

import json
import socket
import sys
import tempfile
import threading
import time
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
PUBLIC = "93.184.216.34"


def fake_dns(internal=()):
    """Every name resolves to a public address, except the ones listed."""
    def getaddrinfo(host, *args, **kwargs):
        return REAL_GETADDRINFO("127.0.0.1" if host in internal else PUBLIC, *args, **kwargs)
    return getaddrinfo


class ResolverNeverWalksInsideTests(unittest.TestCase):
    """End to end, and the control: the resolver from before 2026-10 followed
    a short link without any guard."""

    def test_a_short_link_that_resolves_inside_is_never_requested(self):
        hits = []

        class Recorder(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(301 if self.path == "/abc" else 200)
                if self.path == "/abc":   # a second local hop, so even old code never leaves the machine
                    self.send_header("Location", f"http://short.invalid:{self.server.server_address[1]}/next")
                self.end_headers()

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        hosts = set(extractors._SHORTENER_HOSTS) | {"short.invalid"}
        try:
            with mock.patch.object(socket, "getaddrinfo", fake_dns(internal={"short.invalid"})), \
                    mock.patch.object(extractors, "_SHORTENER_HOSTS", hosts), \
                    mock.patch.dict(extractors._RESOLVE_CACHE, clear=True):
                extractors._resolve_short_link(f"http://short.invalid:{port}/abc")
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(hits, [], "the resolver requested a host that resolves to an internal address")


class HopTests(unittest.TestCase):
    def resolve(self, url, answers):
        calls = []

        def fake_hop(u, timeout=10):
            calls.append(u)
            return answers[u]
        with mock.patch.object(socket, "getaddrinfo", fake_dns()), \
                mock.patch.object(extractors, "_fetch_hop", fake_hop), \
                mock.patch.dict(extractors._RESOLVE_CACHE, clear=True):
            return extractors._resolve_short_link(url), calls

    def test_redirect_to_a_public_destination(self):
        got, calls = self.resolve("https://bit.ly/a", {"https://bit.ly/a": (301, "https://github.com/x/y", "")})
        self.assertEqual(got, "https://github.com/x/y")
        self.assertEqual(calls, ["https://bit.ly/a"])   # the destination itself is never fetched

    def test_lnkd_in_leaving_page_names_the_destination(self):
        page = ('<a class="artdeco-button" data-tracking-control-name="external_url_click" '
                'data-tracking-will-navigate href="https://go.example-tool.dev/launch?a=1&amp;b=2">')
        got, _ = self.resolve("https://lnkd.in/gAbC123", {"https://lnkd.in/gAbC123": (200, None, page)})
        self.assertEqual(got, "https://go.example-tool.dev/launch?a=1&b=2")

    def test_a_hop_to_an_internal_address_is_refused_before_the_request(self):
        got, calls = self.resolve("https://bit.ly/a", {"https://bit.ly/a": (302, "http://127.0.0.1:7778/delete", "")})
        self.assertIsNone(got)
        self.assertEqual(calls, ["https://bit.ly/a"])

    def test_a_hop_to_another_scheme_is_refused(self):
        got, _ = self.resolve("https://bit.ly/a", {"https://bit.ly/a": (302, "file:///etc/passwd", "")})
        self.assertIsNone(got)

    def test_a_chain_longer_than_the_limit_gives_up(self):
        answers = {f"https://bit.ly/{n}": (301, f"https://bit.ly/{n + 1}", "") for n in range(20)}
        got, calls = self.resolve("https://bit.ly/0", answers)
        self.assertIsNone(got)
        self.assertEqual(len(calls), extractors.MAX_SHORT_LINK_HOPS)

    def test_a_failed_lookup_is_tried_again_next_time(self):
        calls = []

        def flaky_hop(u, timeout=10):
            calls.append(u)
            if len(calls) == 1:
                raise OSError("network blip")
            return 301, "https://github.com/x/y", ""
        with mock.patch.object(socket, "getaddrinfo", fake_dns()), \
                mock.patch.object(extractors, "_fetch_hop", flaky_hop), \
                mock.patch.dict(extractors._RESOLVE_CACHE, clear=True):
            first = extractors._resolve_short_link("https://bit.ly/a")
            second = extractors._resolve_short_link("https://bit.ly/a")
            third = extractors._resolve_short_link("https://bit.ly/a")
        self.assertIsNone(first)
        self.assertEqual(second, "https://github.com/x/y", "a failed lookup was cached")
        self.assertEqual(third, second)
        self.assertEqual(len(calls), 2)   # the success is cached

    def test_the_guard_is_the_same_object_in_both_modules(self):
        if server is None:
            self.skipTest("server.py could not be imported here")
        self.assertIs(server._blocked_url_reason, extractors.blocked_url_reason)
        for bad in ("http://127.0.0.1/x", "http://10.1.2.3/", "http://100.100.1.1/", "file:///etc/hosts",
                    "http://localhost:7778/", "http://printer.local/", "https://example.com/"):
            self.assertTrue(server._blocked_url_reason(bad, resolve=False), bad)
        self.assertIsNone(server._blocked_url_reason("https://github.com/x", resolve=False))


class LinkFindingTests(unittest.TestCase):
    def test_find_links_full_and_bare(self):
        text = ("Repo here: https://github.com/a/b. Docs (https://docs.python.org/3/x.html), "
                "and the tool lnkd.in/eXyZ12 plus again https://lnkd.in/eXyZ12 and mail me@lnkd.in/no")
        self.assertEqual(extractors.find_links(text), [
            "https://github.com/a/b", "https://docs.python.org/3/x.html", "https://lnkd.in/eXyZ12"])

    def test_artifact_urls(self):
        text = ("Link in the comments. Top comments: lnkd.in/abc and https://docs.python.org/3/x.html; "
                "mine https://www.linkedin.com/posts/me-activity-1 and http://10.0.0.1/admin")
        targets = {"https://lnkd.in/abc": "https://github.com/x/tool?utm_source=li&tab=readme"}
        with mock.patch.object(socket, "getaddrinfo", fake_dns()), \
                mock.patch.object(extractors, "_resolve_short_link", lambda u: targets.get(u)):
            got = extractors.artifact_urls(text, own_url="https://www.linkedin.com/posts/me-activity-1")
        self.assertEqual(got, ["https://github.com/x/tool?tab=readme", "https://docs.python.org/3/x.html"])

    def test_an_unresolved_short_link_is_left_out(self):
        with mock.patch.object(socket, "getaddrinfo", fake_dns()), \
                mock.patch.object(extractors, "_resolve_short_link", lambda u: None):
            self.assertEqual(extractors.artifact_urls("see lnkd.in/zzz"), [])

    def test_feed_pages_are_containers_and_posts_are_not(self):
        for url in ("https://www.linkedin.com/feed/", "https://www.linkedin.com/feed", "https://linkedin.com/",
                    "https://www.linkedin.com/mynetwork/", "https://www.reddit.com/r/all/",
                    "https://news.ycombinator.com/news"):
            self.assertTrue(extractors.container_page_reason(url), url)
        for url in ("https://www.linkedin.com/feed/update/urn:li:activity:7380000000000000000/",
                    "https://www.linkedin.com/posts/someone_slug-activity-7380000000000000000-AbCd",
                    "https://www.reddit.com/r/ClaudeAI/comments/abc123/"):
            self.assertIsNone(extractors.container_page_reason(url), url)


@unittest.skipIf(server is None, "server.py could not be imported here")
class SaveTests(unittest.TestCase):
    """process_url with the page fetch and the model replaced."""

    ANALYSIS = {"title": "A tool someone built", "summary": "It does a thing for 40 teams.",
                "action_points": ["Try it"], "category": "Tool", "tags": ["cli"], "relevance": 4}

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
        self.page = ("A developer built a small command line tool that turns a messy folder of meeting "
                     "notes into one weekly summary. It reads markdown files, groups them by project, "
                     "counts open decisions, and writes a single page every Friday morning. The author "
                     "says forty teams tried it during the beta, that setup takes about ten minutes, and "
                     "that the next release adds calendar import and a plain text export for archives. "
                     "Source code and install steps: https://github.com/someone/tool-docs and nothing else.")
        self._patches = [
            mock.patch.object(socket, "getaddrinfo", fake_dns()),
            mock.patch.object(server, "fetch_url_content", lambda url: self.page),
            mock.patch.object(server, "analyze_with_ai", lambda url, content: dict(self.ANALYSIS)),
            mock.patch.object(server, "embed_text", lambda text: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def items(self):
        return json.loads(server.DATA_FILE.read_text())["items"]

    def wait_for(self, key, seconds=3.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            items = self.items()
            if items and key in items[0]:
                return items[0]
            time.sleep(0.05)
        return self.items()[0] if self.items() else {}

    def test_a_feed_page_is_flagged_not_saved(self):
        result = server.process_url("https://www.linkedin.com/feed/?trk=nav")
        self.assertEqual(self.items(), [], "a feed page was saved as an item")
        self.assertEqual(result["status"], "failed")
        self.assertIn("feed page", result["reason"])
        failures = json.loads(server.FAILURES_FILE.read_text())["items"]
        self.assertEqual([f["error_type"] for f in failures], ["quality"])

    def test_a_new_save_gets_artifact_urls_after_the_save(self):
        result = server.process_url("https://github.com/someone/tool")
        self.assertEqual(result["status"], "saved")
        item = self.wait_for("artifact_urls")
        self.assertEqual(item.get("artifact_urls"), ["https://github.com/someone/tool-docs"])

    def test_a_link_lookup_failure_never_fails_the_save(self):
        def broken(*args, **kwargs):
            raise RuntimeError("resolver down")
        with mock.patch.object(server, "artifact_urls", broken, create=True):
            result = server.process_url("https://github.com/someone/tool")
            item = self.wait_for("summary_checked")
        self.assertEqual(result["status"], "saved")
        self.assertEqual([i["url"] for i in self.items()], ["https://github.com/someone/tool"])
        # The other post-save step still lands, so the failure was caught
        # inside the step rather than killing it.
        self.assertIn("summary_checked", item, "a failed link lookup took the summary check down with it")
        self.assertNotIn("artifact_urls", item)


if __name__ == "__main__":
    unittest.main()
