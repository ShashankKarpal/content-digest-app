"""knowledge.json and knowledge.html never share a temp file (review, 2026-10).

Both used to be written through with_suffix(".tmp"), which is knowledge.tmp
for each, so a page render racing a data write (the post-save step writes
knowledge.json while /view renders) could rename the HTML over the
knowledge base. All data files are in a temp folder.
Run: python3 -m unittest tests.test_atomic_writes
"""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e


@unittest.skipIf(server is None, "server.py could not be imported here")
class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._saved = {}
        for name in dir(server):
            value = getattr(server, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(server, name, self.dir / value.name)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(server, name, value)
        self.tmp.cleanup()

    def test_page_and_data_use_different_temp_files(self):
        renames = []
        real_rename = Path.rename

        def spy(self_path, target):
            renames.append((Path(self_path).name, Path(target).name))
            return real_rename(self_path, target)
        with mock.patch.object(Path, "rename", spy):
            server._write_html("<html></html>")
            server._save_data({"items": []})
        temp_for = {target: source for source, target in renames}
        self.assertNotEqual(temp_for["knowledge.html"], temp_for["knowledge.json"],
                            "knowledge.html and knowledge.json are written through the same temp file")

    def test_concurrent_page_and_data_writes_keep_the_data_intact(self):
        data = {"items": [{"url": f"https://a.dev/{n}", "title": "t" * 200} for n in range(50)]}
        page = "<html>" + "x" * 50_000 + "</html>"
        errors = []

        def write(fn, arg):
            for _ in range(200):
                try:
                    fn(arg)
                except Exception as e:   # a lost race on rename is the bug showing
                    errors.append(type(e).__name__)
        threads = [threading.Thread(target=write, args=(server._save_data, data)),
                   threading.Thread(target=write, args=(server._write_html, page))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(json.loads(server.DATA_FILE.read_text()), data)
        self.assertEqual(errors, [])
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
