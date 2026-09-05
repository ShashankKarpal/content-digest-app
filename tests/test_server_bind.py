"""Unit tests for the explicit-bind helpers in server.py (audit A8).

Importing server.py runs its module-level setup (reads the gitignored
secrets.json, defines the handler) but starts nothing. The tests skip cleanly
on a machine without the server's dependencies.
Run: python3 -m unittest tests.test_server_bind
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import server  # noqa: E402
except Exception as e:  # pragma: no cover
    server = None
    IMPORT_ERROR = e


@unittest.skipIf(server is None, "server.py could not be imported here")
class BindAddressConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = server.CONFIG_FILE
        server.CONFIG_FILE = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        server.CONFIG_FILE = self._old
        self.tmp.cleanup()

    def test_missing_file_means_default_bind(self):
        self.assertEqual(server._bind_addresses_from_config(), [])

    def test_key_absent_means_default_bind(self):
        server.CONFIG_FILE.write_text(json.dumps({"recipient": "x"}))
        self.assertEqual(server._bind_addresses_from_config(), [])

    def test_valid_addresses_are_kept_and_junk_dropped(self):
        server.CONFIG_FILE.write_text(json.dumps({"bind_addresses": ["127.0.0.1", " 100.64.0.1 ", "not-an-ip", 7]}))
        self.assertEqual(server._bind_addresses_from_config(), ["127.0.0.1", "100.64.0.1"])

    def test_non_list_is_ignored(self):
        server.CONFIG_FILE.write_text(json.dumps({"bind_addresses": "127.0.0.1"}))
        self.assertEqual(server._bind_addresses_from_config(), [])

    def test_unreadable_json_means_default_bind(self):
        server.CONFIG_FILE.write_text("{not json")
        self.assertEqual(server._bind_addresses_from_config(), [])


@unittest.skipIf(server is None, "server.py could not be imported here")
class BindServersTests(unittest.TestCase):
    def test_loopback_binds_on_an_ephemeral_port(self):
        servers = server._bind_servers(["127.0.0.1"], 0, server.Handler, retry_seconds=0)
        try:
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].server_address[0], "127.0.0.1")
        finally:
            for s in servers:
                s.server_close()

    def test_unassigned_address_is_skipped_after_retries(self):
        # 203.0.113.1 is TEST-NET-3: never assigned to a local interface.
        servers = server._bind_servers(["203.0.113.1"], 0, server.Handler, retry_seconds=0)
        self.assertEqual(servers, [])

    def test_retry_until_the_address_appears(self):
        attempts = {"n": 0}
        sleeps = []

        class Flaky:
            def __init__(self, address, handler):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise OSError(49, "Can't assign requested address")
                self.server_address = address

        servers = server._bind_servers(["100.64.0.9"], 7778, object, retry_seconds=60, delay=5,
                                       server_cls=Flaky, sleep=sleeps.append)
        self.assertEqual(len(servers), 1)
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(sleeps, [5, 5])

    def test_one_dead_address_does_not_stop_the_others(self):
        servers = server._bind_servers(["203.0.113.1", "127.0.0.1"], 0, server.Handler, retry_seconds=0)
        try:
            self.assertEqual([s.server_address[0] for s in servers], ["127.0.0.1"])
        finally:
            for s in servers:
                s.server_close()


if __name__ == "__main__":
    unittest.main()
