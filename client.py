#!/usr/bin/env python3
"""Content Digest Client -- lightweight menu bar app that sends URLs to M1 server."""

import json
import subprocess
import time
import urllib.request
import webbrowser
import rumps

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_settings import SERVER
except ImportError:
    SERVER = "http://127.0.0.1:7778"

# D1 watchdog (2026-09-05): this client is the observer for the remote runtime.
# It polls /health every HEALTH_POLL_SECONDS without credentials (so a poll
# never counts as user contact on the server), posts ONE banner after
# MISSES_BEFORE_ALERT consecutive misses, marks the menu bar item, and posts
# one recovery banner when the server answers again. The two environment
# variables exist so the behaviour can be exercised from a Terminal against a
# closed port without touching the LaunchAgent.
HEALTH_URL = os.environ.get("CD_HEALTH_URL") or f"{SERVER}/health"
HEALTH_POLL_SECONDS = int(os.environ.get("CD_HEALTH_POLL_SECONDS") or 900)
MISSES_BEFORE_ALERT = 2

# Auth token lives in gitignored secrets.json, never hardcoded here.
try:
    _secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json")
    AUTH_TOKEN = json.load(open(_secrets_path)).get("auth_token", "")
except Exception:
    AUTH_TOKEN = ""


def request_notify_authorization():
    """Ask the modern notification centre for banner and sound rights.

    Runs once at startup from the Content Digest.app bundle (2026-08-24
    decision log). First launch prompts; the answer is keyed to the bundle
    identifier com.shashank.contentdigest. Failures print to stderr, which
    the LaunchAgent routes to ~/contentdigest-client.log, because a silent
    notification failure is how switchdeck lost banners for a year."""
    try:
        import UserNotifications as UN
        center = UN.UNUserNotificationCenter.currentNotificationCenter()

        def _cb(granted, error):
            print("notify authorization granted=%s error=%s" % (granted, error),
                  file=sys.stderr, flush=True)

        opts = UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound
        center.requestAuthorizationWithOptions_completionHandler_(opts, _cb)
    except Exception as e:
        print("notify authorization request failed: %r" % e,
              file=sys.stderr, flush=True)


def notify(title, subtitle, message):
    """Banner plus default sound via the modern centre, falling back to the
    legacy rumps path with evidence on stderr. Legacy NSUserNotification on
    macOS 26 files notifications without presenting them unless the modern
    authorization exists, so the modern path goes first."""
    try:
        import UserNotifications as UN
        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(str(title))
        content.setSubtitle_(str(subtitle))
        content.setBody_(str(message))
        content.setSound_(UN.UNNotificationSound.defaultSound())
        import time as _t
        req = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            "contentdigest-%f" % _t.time(), content, None)

        def _cb(error):
            if error:
                print("notify post error: %s" % error, file=sys.stderr, flush=True)

        UN.UNUserNotificationCenter.currentNotificationCenter() \
            .addNotificationRequest_withCompletionHandler_(req, _cb)
        return
    except Exception as e:
        print("modern notify failed (%r), trying legacy" % e,
              file=sys.stderr, flush=True)
    try:
        rumps.notification(title, subtitle, message)
    except Exception as e:
        print("legacy notify failed too: %r" % e, file=sys.stderr, flush=True)


class ContentDigestClient(rumps.App):
    def __init__(self):
        # Brand symbol as a macOS template icon (auto light/dark). Falls back
        # to the classic pin emoji if the icon file is missing.
        _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "design", "logo", "menubar-template.png")
        if os.path.exists(_icon):
            super().__init__("Content Digest", icon=_icon, template=True, quit_button=None)
        else:
            super().__init__("📌", quit_button=None)
        self.status_item = rumps.MenuItem("Server: not checked yet")
        self.status_item.set_callback(None)
        self.menu = [
            rumps.MenuItem("Add URL...", callback=self.add_url),
            rumps.MenuItem("View Knowledge Base", callback=self.view_kb),
            None,
            self.status_item,
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]
        self.misses = 0
        self.down_since = None
        self.alerted = False
        self.health_timer = rumps.Timer(self.check_health, HEALTH_POLL_SECONDS)
        self.health_timer.start()

    # --- watchdog -----------------------------------------------------------

    def _probe(self):
        """GET /health with no credentials. Returns (ok, detail)."""
        try:
            req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "content-digest-client"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode() or "{}")
            return bool(body.get("ok")), body
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def check_health(self, _=None):
        ok, detail = self._probe()
        stamp = time.strftime("%H:%M")
        if ok:
            was_down = self.alerted
            self.misses = 0
            self.down_since = None
            self.alerted = False
            self.title = None  # clear the marker beside the icon
            contact = (detail.get("last_client_contact_at") or "")[:16].replace("T", " ") if isinstance(detail, dict) else ""
            self.status_item.title = f"Server: ok at {stamp}" + (f", last capture contact {contact}" if contact else "")
            if was_down:
                notify("Content Digest", "Server is back", f"Reachable again at {stamp}.")
                print(f"watchdog: recovered at {stamp}", file=sys.stderr, flush=True)
            return
        self.misses += 1
        self.down_since = self.down_since or stamp
        self.status_item.title = f"Server: unreachable since {self.down_since} ({self.misses} checks)"
        print(f"watchdog: miss {self.misses} at {stamp}: {detail}", file=sys.stderr, flush=True)
        if self.misses >= MISSES_BEFORE_ALERT and not self.alerted:
            self.alerted = True
            self.title = "!"  # visible marker next to the menu bar icon, no new asset needed
            minutes = (self.misses * HEALTH_POLL_SECONDS) // 60
            print(f"watchdog: alert posted at {stamp} after {self.misses} misses", file=sys.stderr, flush=True)
            notify("Content Digest", "Server unreachable",
                   f"No answer for about {minutes} min ({self.misses} checks). "
                   "If Tailscale is off on this Mac or the phone, saves are not arriving.")

    def add_url(self, _):
        script = '''tell application "System Events"
            activate
            set userInput to text returned of (display dialog "Paste a URL to save and summarize:" default answer "https://" with title "Content Digest" buttons {"Cancel", "Save"} default button "Save")
        end tell
        return userInput'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode != 0:
            return
        url = result.stdout.strip()
        if not url.startswith(("http://", "https://")):
            rumps.alert("Invalid URL", "Please enter a valid URL starting with http:// or https://")
            return
        try:
            body = json.dumps({"url": url}).encode()
            req = urllib.request.Request(
                f"{SERVER}/add",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {AUTH_TOKEN}",
                    "X-Client": "mac-client",
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                json.loads(resp.read().decode())
            notify("Content Digest", "URL sent", f"Processing: {url[:60]}")
        except Exception as e:
            notify("Content Digest", "Error", f"Could not reach server: {e}")

    def view_kb(self, _):
        # Plain /view: the session cookie does the work after the first unlock.
        # The token used to ride in this URL on every click and so sat in the
        # browser history; a browser that is not yet unlocked now gets the
        # server's Locked page and asks for the token once (audit A5, 2026-09-05).
        webbrowser.open(f"{SERVER}/view")

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    request_notify_authorization()
    ContentDigestClient().run()
