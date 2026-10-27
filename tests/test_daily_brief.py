"""Unit tests for the slim morning brief (decision 14, 2026-10) and its
host-health line.

No network and no SMTP: send_email is replaced by a recorder and every data
file daily_brief.py names points into a temp folder.
Run: python3 -m unittest tests.test_daily_brief
"""

import json
import ssl
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import daily_brief as db  # noqa: E402

TZ = timezone(timedelta(hours=4))
NOW = datetime(2026, 9, 7, 7, 0, tzinfo=TZ)
LONG = ("This post explains how a small team moved their build from one machine to a fleet "
        "of runners, what it cost, which three mistakes they made on the way, and the one "
        "setting that halved their queue time. It ends with a checklist.")


def _item(url, saved_days_ago=30, **fields):
    it = {"url": url, "title": url, "category": "Work", "state": "",
          "saved_at": (NOW - timedelta(days=saved_days_ago)).isoformat()}
    it.update(fields)
    return it


class SmtpTlsTests(unittest.TestCase):
    """The Gmail login must run over TLS that checks the server certificate:
    smtplib's default context verifies nothing, which would hand the app
    password to anyone who can intercept the connection."""

    def test_send_email_verifies_the_server_certificate(self):
        config = {"smtp_user": "sender@example.invalid", "recipient": "reader@example.invalid",
                  "smtp_password": "abcd efgh"}
        with mock.patch.object(db.smtplib, "SMTP_SSL") as smtp:
            db.send_email(config, "subject", "<p>body</p>")
        smtp.assert_called_once()
        kwargs = smtp.call_args.kwargs
        context = kwargs.get("context")
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0, "no trusted root certificates loaded")
        self.assertTrue(kwargs.get("timeout"), "a stalled connection must not hang the job")


class SlimBodyTests(unittest.TestCase):
    def test_two_lines_cuts_at_a_word_boundary(self):
        self.assertEqual(db.two_lines("Short summary."), "Short summary.")
        cut = db.two_lines(LONG)
        self.assertTrue(cut.endswith("..."))
        self.assertLessEqual(len(cut), db.SUMMARY_CHARS + 3)
        self.assertTrue(LONG.startswith(cut[:-3]))
        self.assertNotIn("  ", db.two_lines("a\n\nb   c"))

    def test_card_has_title_link_category_and_two_line_summary_only(self):
        item = {"url": "https://example.org/build", "title": "Fleet builds", "category": "Learning",
                "summary": LONG, "action_points": ["Do the thing"], "tags": ["ci", "fleet"],
                "relevance": 5, "state": "revisit", "saved_at": NOW.isoformat()}
        body = db.format_email_body([item], NOW)
        self.assertIn('href="https://example.org/build"', body)
        self.assertIn("Fleet builds", body)
        self.assertIn("Learning", body)
        self.assertIn(db.two_lines(LONG), body)
        for gone in ("Do the thing", "Action Pointers", ">ci<", "REVISIT LATER", "Read Article",
                     "&#9679;", "Top tags", "/triage", "FROM YOUR BACKLOG", "aged out", "Loop this week"):
            self.assertNotIn(gone, body)

    def test_titles_and_links_are_escaped(self):
        item = {"url": "javascript:alert(1)", "title": "<script>x</script>", "category": "Ideas",
                "summary": "s", "saved_at": NOW.isoformat()}
        body = db.format_email_body([item], NOW)
        self.assertNotIn("<script>x", body)
        self.assertNotIn("javascript:", body)

    def test_newest_save_comes_first(self):
        a = _item("https://a", saved_days_ago=0.5, title="older")
        b = _item("https://b", saved_days_ago=0.1, title="newer")
        body = db.format_email_body([a, b], NOW)
        self.assertLess(body.index("newer"), body.index("older"))


class MainTests(unittest.TestCase):
    """main() end to end with SMTP replaced: one recent save, many old ones."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = {}
        for name in dir(db):
            value = getattr(db, name)
            if name.endswith("_FILE") and isinstance(value, Path):
                self._saved[name] = value
                setattr(db, name, d / value.name)
        self.dir = d
        now = datetime.now(TZ)
        items = [{"url": "https://example.org/new", "title": "New one", "category": "Work",
                  "summary": "Fresh.", "state": "", "relevance": 3,
                  "saved_at": (now - timedelta(hours=2)).isoformat()}]
        items += [{"url": f"https://example.org/old/{n}", "title": f"Old {n}", "category": c,
                   "summary": "Old.", "state": "", "relevance": 5,
                   "saved_at": (now - timedelta(days=40 + n)).isoformat()}
                  for n, c in enumerate(["Work", "Ideas", "News", "Learning"])]
        db.KNOWLEDGE_FILE.write_text(json.dumps({"items": items}))
        db.CONFIG_FILE.write_text(json.dumps({"smtp_user": "u@example.org", "smtp_password": "p",
                                              "recipient": "r@example.org",
                                              "server_base": "http://127.0.0.1:7778"}))
        (d / "secrets.json").write_text(json.dumps({"auth_token": "t" * 40}))
        db.CLIENTS_FILE.write_text(json.dumps({"shortcut": now.isoformat()}))
        self.sent = []

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(db, name, value)
        self.tmp.cleanup()

    def run_main(self, *args):
        with mock.patch.object(db, "send_email", side_effect=lambda c, s, b: self.sent.append((s, b))), \
                mock.patch.object(sys, "argv", ["daily_brief.py", *args]):
            return db.main()

    def test_brief_is_only_the_new_save(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.sent), 1)
        subject, body = self.sent[0]
        self.assertTrue(subject.endswith(": 1 save"), subject)
        self.assertIn("New one", body)
        for n in range(4):
            self.assertNotIn(f"Old {n}", body, "a backlog item was resurfaced")
        self.assertNotIn("/triage", body)
        self.assertNotIn("FROM YOUR BACKLOG", body)

    def test_no_fatigue_ledger_is_written(self):
        self.run_main()
        self.assertFalse((self.dir / "resurface.json").exists(), "the retired fatigue ledger was written")
        self.assertFalse((self.dir / "loopcheck-history.txt").exists())

    def test_weekly_flag_sends_nothing(self):
        self.assertEqual(self.run_main("--weekly"), 0)
        self.assertEqual(self.sent, [])

    def test_dry_run_sends_nothing_and_renders(self):
        self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("New one", db.LAST_RENDER_FILE.read_text())


class HostHealthTests(unittest.TestCase):
    def test_healthy_when_save_and_contact_are_recent(self):
        items = [_item("https://a", saved_days_ago=1)]
        clients = {"extension": (NOW - timedelta(hours=5)).isoformat()}
        hh = db.host_health(items, clients, NOW)
        self.assertFalse(hh["stale"])
        self.assertEqual(hh["contact_gap_hours"], 5)
        self.assertEqual(db.format_host_health_line(hh), "")

    def test_stale_when_no_contact_for_48h(self):
        items = [_item("https://a", saved_days_ago=1)]
        clients = {"mac-client": (NOW - timedelta(hours=49)).isoformat()}
        hh = db.host_health(items, clients, NOW)
        self.assertTrue(hh["stale"])
        line = db.format_host_health_line(hh)
        self.assertIn("Host health", line)
        self.assertIn("49", line)

    def test_stale_when_no_save_for_48h_even_with_contact(self):
        items = [_item("https://a", saved_days_ago=3)]
        clients = {"extension": NOW.isoformat()}
        hh = db.host_health(items, clients, NOW)
        self.assertTrue(hh["stale"])
        self.assertEqual(hh["save_gap_hours"], 72)

    def test_missing_clients_file_is_never_seen(self):
        hh = db.host_health([], {}, NOW)
        self.assertIsNone(hh["last_contact_at"])
        self.assertTrue(hh["stale"])
        self.assertIn("never", db.format_host_health_line(hh))

    def test_health_line_rides_the_brief_when_stale(self):
        hh = db.host_health([_item("https://a", saved_days_ago=3)], {}, NOW)
        line = db.format_host_health_line(hh)
        self.assertIn(line, db.format_email_body([_item("https://b", saved_days_ago=0)], NOW, line))
        self.assertIn(line, db.format_empty_email_body(NOW, 10, line))


if __name__ == "__main__":
    unittest.main()
