"""Local models only (2026-10): the Groq cloud fallback is gone.

With Ollama down, a summary must fail on the host (an "ai" failure the retry
sweep picks up) and an Ask must answer with the closest matches. Neither may
send the page text or the question to any other endpoint. Network is mocked:
every urlopen call is recorded and refused.
Run: python3 -m unittest tests.test_local_only
"""

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e

OLLAMA = "http://localhost:11434/"


def refuse_all(calls):
    def fake_urlopen(req, *args, **kwargs):
        calls.append(getattr(req, "full_url", str(req)))
        raise urllib.error.URLError("network disabled in tests")
    return fake_urlopen


@unittest.skipIf(server is None, "server.py could not be imported here")
class LocalOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = server.DATA_FILE
        server.DATA_FILE = Path(self.tmp.name) / "knowledge.json"
        server.DATA_FILE.write_text(json.dumps({"items": [
            {"url": "https://example.org/k8s", "title": "Kubernetes upgrade notes",
             "summary": "How to upgrade a Kubernetes cluster.", "tags": ["kubernetes"]}]}))

    def tearDown(self):
        server.DATA_FILE = self._old
        self.tmp.cleanup()

    def test_summary_fails_on_the_host_when_ollama_is_down(self):
        calls = []
        with mock.patch("urllib.request.urlopen", refuse_all(calls)):
            with self.assertRaises(Exception):
                server.analyze_with_ai("https://example.org/a", "page text " * 60)
        self.assertTrue(calls, "the local model should have been tried")
        self.assertEqual([u for u in calls if not u.startswith(OLLAMA)], [])

    def test_ask_answers_with_matches_when_ollama_is_down(self):
        calls = []
        with mock.patch("urllib.request.urlopen", refuse_all(calls)):
            result = server.answer_question("what did I save about kubernetes?")
        self.assertEqual([u for u in calls if not u.startswith(OLLAMA)], [])
        self.assertIn("closest matches", result["answer"])
        self.assertEqual([s["url"] for s in result["sources"]], ["https://example.org/k8s"])

    def test_no_cloud_endpoint_is_left_in_the_server(self):
        source = Path(server.__file__).read_text()
        self.assertFalse("api.groq.com" in source, "a cloud endpoint is still in server.py")
        self.assertFalse(hasattr(server, "_try_groq"))
        self.assertFalse(hasattr(server, "GROQ_API_KEY"))


if __name__ == "__main__":
    unittest.main()
