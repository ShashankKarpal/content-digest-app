"""v0.6 truth checks (decision 14, 2026-10): the version the server reports
and the docs that describe the product. The README must not describe a
retired feature (zero mentions of triage or resurfacing was the sitting's
written done-check), the decision log carries decision 14, and the current
phase names its success signal.
Run: python3 -m unittest tests.test_docs_v06
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e


class DocsTests(unittest.TestCase):
    def test_readme_describes_no_retired_feature(self):
        readme = (ROOT / "README.md").read_text()
        for retired in ("triage", "resurfac", "Loop this week", "auto-archive decay", "Groq"):
            hits = [line for line in readme.splitlines() if re.search(retired, line, re.I)]
            self.assertEqual(hits, [], f"README still mentions {retired!r}")
        self.assertIn("status-v0.6", readme)

    def test_decision_log_has_decision_14(self):
        log = (ROOT / "docs" / "decision-log.md").read_text()
        self.assertIn("## 2026-09-30 | Product | Keep capture and the knowledge base; "
                      "retire triage and resurfacing (decision 14)", log)
        self.assertIn("retire one-at-a-time triage and resurfacing, run a monthly", log)

    def test_current_phase_names_the_success_signal(self):
        phase = (ROOT / "docs" / "current-phase.md").read_text()
        self.assertIn("## Current Version: v0.6", phase)
        self.assertIn("at least one item the owner acts on per quarter", phase)

    @unittest.skipIf(server is None, "server.py could not be imported here")
    def test_the_server_reports_version_0_6(self):
        self.assertEqual(server.SERVER_VERSION, "0.6")
        self.assertEqual(server.health_snapshot()["version"], "0.6")


if __name__ == "__main__":
    unittest.main()
