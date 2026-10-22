"""The Tool category (decision 14, 2026-10): whitelist, classifier prompt,
knowledge base filter, and the one-time move of the 48 BUILT items.
Run: python3 -m unittest tests.test_tool_category
"""

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

TZ = timezone(timedelta(hours=4))
NOW = datetime(2026, 10, 22, 14, 0, tzinfo=TZ)


def sha(url):
    return hashlib.sha256(url.encode()).hexdigest()


@unittest.skipIf(server is None, "server.py could not be imported here")
class ToolCategoryTests(unittest.TestCase):
    def test_the_model_may_answer_tool(self):
        clean = server.validate_analysis({"title": "t", "summary": "s", "category": "tool"}, "https://x")
        self.assertEqual(clean["category"], "Tool")

    def test_the_prompt_offers_tool_first(self):
        prompt = server._build_prompt("https://x", "text")
        self.assertIn("one of: Tool,", prompt)
        self.assertIn("1. TOOL: a tool, app, repo, extension or product someone built and linked", prompt)

    def test_the_knowledge_base_can_filter_tool(self):
        self.assertIn('data-cat="Tool"', server.build_html([], failures=[]))


class ToolMigrationTests(unittest.TestCase):
    def setUp(self):
        import migrations
        self.m = migrations
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.items = [
            {"url": "https://example.org/repo", "category": "Work", "state": "archive",
             "auto_archived_at": "2026-09-20T07:00:00+04:00", "state_source": "decay"},
            {"url": "https://example.org/app", "category": "News", "state": ""},
            {"url": "https://example.org/already", "category": "Tool", "state": ""},
            {"url": "https://example.org/other", "category": "Ideas", "state": ""},
        ]
        self.listed = frozenset({sha("https://example.org/repo"), sha("https://example.org/app"),
                                 sha("https://example.org/already"), sha("https://example.org/deleted-since")})

    def tearDown(self):
        self.tmp.cleanup()

    def test_listed_items_move_to_tool_and_keep_their_old_category(self):
        with mock.patch.object(self.m, "TOOL_URL_SHA256", self.listed):
            counts = self.m.recategorize_built_as_tool(self.items, NOW)
        cats = {i["url"]: i["category"] for i in self.items}
        self.assertEqual(cats["https://example.org/repo"], "Tool")
        self.assertEqual(cats["https://example.org/app"], "Tool")
        self.assertEqual(cats["https://example.org/other"], "Ideas")
        self.assertEqual(self.items[0]["category_history"],
                         [{"category": "Work", "changed_at": NOW.isoformat(), "by": "2026-10-tool-category"}])
        self.assertNotIn("category_history", self.items[2])
        self.assertEqual(counts, {"listed": 4, "recategorized": 2, "already_tool": 1,
                                  "not_found": 1, "from": {"Work": 1, "News": 1}})

    def test_running_it_again_changes_nothing(self):
        with mock.patch.object(self.m, "TOOL_URL_SHA256", self.listed):
            self.m.recategorize_built_as_tool(self.items, NOW)
            snapshot = json.dumps(self.items, sort_keys=True)
            counts = self.m.recategorize_built_as_tool(self.items, NOW)
        self.assertEqual(json.dumps(self.items, sort_keys=True), snapshot)
        self.assertEqual(counts["recategorized"], 0)
        self.assertEqual(counts["already_tool"], 3)

    def test_the_shipped_list_is_48_hashes(self):
        self.assertEqual(len(self.m.TOOL_URL_SHA256), 48)
        self.assertTrue(all(len(h) == 64 and int(h, 16) >= 0 for h in self.m.TOOL_URL_SHA256))

    def test_one_start_applies_both_migrations_with_one_backup(self):
        (self.dir / "knowledge.json").write_text(json.dumps({"items": self.items}))
        with mock.patch.object(self.m, "TOOL_URL_SHA256", self.listed):
            results = self.m.run(self.dir, now=NOW, log=lambda line: None)
        self.assertEqual(list(results), ["2026-10-decay-restore", "2026-10-tool-category"])
        repo = json.loads((self.dir / "knowledge.json").read_text())["items"][0]
        self.assertEqual((repo["state"], repo["category"]), ("", "Tool"))
        self.assertEqual(len(list(self.dir.glob("knowledge.json.pre-migration-*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
