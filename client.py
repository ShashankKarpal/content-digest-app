#!/usr/bin/env python3
"""Content Digest Client -- lightweight menu bar app that sends URLs to M1 server."""

import json
import subprocess
import urllib.request
import webbrowser
import rumps

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_settings import SERVER
except ImportError:
    SERVER = "http://127.0.0.1:7778"

# Auth token lives in gitignored secrets.json, never hardcoded here.
try:
    _secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json")
    AUTH_TOKEN = json.load(open(_secrets_path)).get("auth_token", "")
except Exception:
    AUTH_TOKEN = ""


class ContentDigestClient(rumps.App):
    def __init__(self):
        super().__init__("📌", quit_button=None)
        self.menu = [
            rumps.MenuItem("Add URL...", callback=self.add_url),
            rumps.MenuItem("View Knowledge Base", callback=self.view_kb),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

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
                    "Authorization": f"Bearer {AUTH_TOKEN}"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                json.loads(resp.read().decode())
            rumps.notification("Content Digest", "URL sent", f"Processing: {url[:60]}")
        except Exception as e:
            rumps.notification("Content Digest", "Error", f"Could not reach server: {e}")

    def view_kb(self, _):
        webbrowser.open(f"{SERVER}/view")

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    ContentDigestClient().run()
