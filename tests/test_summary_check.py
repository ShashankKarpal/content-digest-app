"""Summary self-check without a model (decision 14, red-teamed 2026-10):
every name and number in a summary must appear in the text it was made from.
It runs after the save and can never fail one. No network.
Run: python3 -m unittest tests.test_summary_check
"""

import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

SOURCE = ("Anthropic released Claude Code 2.0 to 1,200 teams this week. The GitHub repo passed 60K stars, "
          "and the Notions clipboard trick drew a 3.5x speed-up. LLM costs fell 40% for the beta group.")


@unittest.skipIf(server is None, "server.py could not be imported here")
class CheckTests(unittest.TestCase):
    def check(self, summary, source=SOURCE):
        return server.check_summary(summary, source)

    def test_a_faithful_summary_passes(self):
        r = self.check("The team shipped Claude Code 2.0 to 1,200 teams; GitHub stars passed 60K, "
                       "costs fell 40% and Notion's clipboard was 3.5x faster.")
        self.assertEqual(r["missing"], [])
        self.assertTrue(r["ok"])
        self.assertEqual((r["names"], r["numbers"]), (4, 5))   # claude code github notion; 2.0 1200 60 40 3.5

    def test_invented_names_and_numbers_are_listed(self):
        r = self.check("Built by OpenAI and Microsoft, it reached 5,000 teams in 2026 and 1,200 stars.")
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing"], ["OpenAI", "Microsoft", "5,000", "2026"])

    def test_plain_words_opening_a_sentence_are_not_names(self):
        r = self.check("Overall the release matters. Teams should try it.\n- Key point: Install it.")
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["names"], 0)

    def test_acronyms_and_inner_capitals_count_even_at_the_start(self):
        r = self.check("AWS hosts it. OpenAI is not involved. iPhone apps follow.")
        self.assertEqual(r["missing"], ["AWS", "OpenAI", "iPhone"])

    def test_generic_acronyms_and_single_digits_are_skipped(self):
        r = self.check("An AI tool with an API and 3 modes, built on an LLM.")
        self.assertEqual(r["missing"], [])
        self.assertEqual((r["names"], r["numbers"]), (0, 0))

    def test_hyphenated_and_possessive_forms(self):
        self.assertEqual(self.check("A Claude-based helper; GitHub's API.")["missing"], [])
        self.assertEqual(self.check("A Rust-based helper.")["missing"], ["Rust"])

    def test_missing_is_capped(self):
        names = " ".join(f"Name{n}x" for n in range(30))
        r = self.check("We met " + names + ".")
        self.assertEqual(len(r["missing"]), server.SUMMARY_CHECK_MISSING_MAX)

    def test_empty_inputs(self):
        self.assertTrue(self.check("", "")["ok"])
        self.assertEqual(self.check("Uses Kubernetes.", "")["missing"], ["Kubernetes"])

    def test_the_card_shows_what_was_not_found(self):
        flagged = {"url": "https://a.dev/x", "title": "t", "summary": "s", "category": "Work",
                   "summary_checked": {"ok": False, "missing": ["OpenAI", "5,000"]}}
        clean = dict(flagged, url="https://a.dev/y", summary_checked={"ok": True, "missing": []})
        page = server.build_html([flagged, clean], failures=[])
        self.assertIn("Not found in the source text: ", page)
        self.assertIn("summary_checked", page)


@unittest.skipIf(server is None, "server.py could not be imported here")
class AfterTheSaveTests(unittest.TestCase):
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
        page = SOURCE + " " + ("The post then walks through setup, pricing, limits and the roadmap in detail. " * 3)
        analysis = {"title": "Claude Code 2.0", "summary": "Anthropic and OpenAI shipped it to 9,999 teams.",
                    "action_points": [], "category": "News", "tags": [], "relevance": 3}
        real = socket.getaddrinfo
        self._patches = [
            mock.patch.object(socket, "getaddrinfo", lambda h, *a, **k: real("93.184.216.34", *a, **k)),
            mock.patch.object(server, "fetch_url_content", lambda url: page),
            mock.patch.object(server, "analyze_with_ai", lambda url, content: dict(analysis)),
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

    def saved_item(self, key, seconds=3.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            items = json.loads(server.DATA_FILE.read_text())["items"]
            if items and key in items[0]:
                return items[0]
            time.sleep(0.05)
        items = json.loads(server.DATA_FILE.read_text())["items"]
        return items[0] if items else {}

    def test_a_new_save_records_the_check(self):
        self.assertEqual(server.process_url("https://news.ycombinator.com/item?id=1")["status"], "saved")
        item = self.saved_item("summary_checked")
        self.assertIn("summary_checked", item, "no summary_checked on a new save")
        self.assertEqual(item["summary_checked"]["missing"], ["OpenAI", "9,999"])

    def test_a_save_that_lost_the_race_starts_no_post_save_steps(self):
        url = "https://news.ycombinator.com/item?id=3"
        first = {"url": url, "title": "Saved first", "summary": "The first save's summary.",
                 "category": "News", "tags": [], "state": "", "saved_at": "2026-10-22T10:00:00+04:00"}
        slow_analysis = {"title": "Saved second", "summary": "Anthropic and OpenAI shipped it to 9,999 teams.",
                         "action_points": [], "category": "News", "tags": [], "relevance": 3}

        def analyze_while_another_save_lands(u, content):
            server.DATA_FILE.write_text(json.dumps({"items": [first]}))   # the other request wins
            return dict(slow_analysis)
        with mock.patch.object(server, "analyze_with_ai", analyze_while_another_save_lands):
            result = server.process_url(url)
            time.sleep(0.5)   # time for any post-save thread to land
        stored = json.loads(server.DATA_FILE.read_text())["items"]
        self.assertEqual(len(stored), 1)
        self.assertNotIn("summary_checked", stored[0], "the losing call checked the wrong summary onto the item")
        self.assertEqual(result["status"], "already_saved")

    def test_a_broken_check_never_fails_the_save(self):
        def broken(*args, **kwargs):
            raise RuntimeError("check crashed")
        with mock.patch.object(server, "check_summary", broken, create=True):
            result = server.process_url("https://news.ycombinator.com/item?id=2")
            item = self.saved_item("artifact_urls")
        self.assertEqual(result["status"], "saved")
        self.assertNotIn("summary_checked", item)
        self.assertIn("artifact_urls", item)   # the other step still landed


if __name__ == "__main__":
    unittest.main()
