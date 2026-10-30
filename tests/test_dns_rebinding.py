"""A name that changes its answer between the guard and the connection never
reaches the network inside (DNS rebinding, leak audit M4, 2026-10).

blocked_url_reason asked DNS where a name points and the connection asked
again, so a name answering a public address first and loopback second got
through. Now each fetch resolves once at connect time, checks every address,
and dials an address it checked. Fake DNS answers a public address on the
first lookup of rebind.invalid and loopback after that; a raw local listener
counts every TCP connection, so plain HTTP and TLS are both covered.
Run: python3 -m unittest tests.test_dns_rebinding
"""

import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extractors  # noqa: E402

REAL_GETADDRINFO = socket.getaddrinfo
PUBLIC = "93.184.216.34"


class RebindingTests(unittest.TestCase):
    def setUp(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.accepted = []
        self._stop = threading.Event()

        def accept_loop():
            while not self._stop.is_set():
                try:
                    conn, _ = self.listener.accept()
                except (socket.timeout, OSError):
                    continue
                self.accepted.append(1)
                conn.close()
        self.thread = threading.Thread(target=accept_loop, daemon=True)
        self.thread.start()

        self.lookups = []
        lookups = self.lookups

        def rebinding_dns(host, port, *args, **kwargs):
            lookups.append((host, port))
            first = sum(1 for h, _ in lookups if h == host) == 1
            answer = PUBLIC if (host == "rebind.invalid" and first) else "127.0.0.1"
            return REAL_GETADDRINFO(answer, port, *args, **kwargs)
        self._dns = mock.patch.object(socket, "getaddrinfo", rebinding_dns)
        self._dns.start()

    def tearDown(self):
        self._dns.stop()
        self._stop.set()
        self.thread.join(2)
        self.listener.close()

    def test_an_extractor_fetch_never_connects_after_a_rebind(self):
        with self.assertRaises(Exception):
            extractors._get(f"http://rebind.invalid:{self.port}/secret", timeout=3)
        self.assertEqual(self.accepted, [], "the fetch connected to the address the name rebound to")

    def test_a_tls_fetch_never_connects_after_a_rebind(self):
        with self.assertRaises(Exception):
            extractors._get(f"https://rebind.invalid:{self.port}/secret", timeout=3)
        self.assertEqual(self.accepted, [], "the TLS fetch connected to the address the name rebound to")

    def test_a_short_link_hop_never_connects_after_a_rebind(self):
        # As _resolve_short_link does it: the guard first, then the hop.
        url = f"http://rebind.invalid:{self.port}/x"
        self.assertIsNone(extractors.blocked_url_reason(url), "the first answer is public")
        with self.assertRaises(Exception):
            extractors._fetch_hop(url, timeout=3)
        self.assertEqual(self.accepted, [], "the short-link hop connected to the address the name rebound to")


class DialTests(unittest.TestCase):
    def test_the_connection_dials_the_address_it_checked(self):
        lookups, dialled = [], []

        def public_dns(host, port, *args, **kwargs):
            lookups.append((host, port))
            return REAL_GETADDRINFO(PUBLIC, port, *args, **kwargs)

        def record_dial(family, socktype, proto, sockaddr, timeout, source_address):
            dialled.append(sockaddr[:2])
            raise OSError("stop here: no network in tests")

        with mock.patch.object(socket, "getaddrinfo", public_dns), \
                mock.patch.object(extractors, "_dial", record_dial):
            with self.assertRaises(Exception):
                extractors._get("http://good.invalid:8080/page", timeout=3)
        self.assertEqual(dialled, [(PUBLIC, 8080)])
        self.assertEqual([p for _, p in lookups if p is not None], [8080],
                         "the connection resolved the name more than once")


if __name__ == "__main__":
    unittest.main()
