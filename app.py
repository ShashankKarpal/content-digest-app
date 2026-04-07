#!/usr/bin/env python3
"""Content Digest — Mac menu bar app for saving and summarizing URLs."""

import json
import re
import threading
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

import rumps
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from AppKit import NSApp

BASE_DIR = Path.home() / "content-digest-app"
DATA_FILE = BASE_DIR / "knowledge.json"
HTML_FILE = BASE_DIR / "knowledge.html"
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL = "qwen2.5-14b-instruct-1m"


def _load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"items": []}


def _save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(DATA_FILE)


def fetch_url_content(url):
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        if not text:
            return None
        return text[:3000]
    except Exception as e:
        return None


def analyze_with_lmstudio(url, content):
    prompt = f"""Analyze this saved article or post. Return ONLY a JSON object, no other text, no markdown.

URL: {url}
Content: {content[:2000]}

Return exactly this JSON:
{{
  "title": "short descriptive title max 10 words",
  "summary": "detailed summary of 150-200 words explaining what this is about, key points, and why it matters",
  "action_points": ["specific action or takeaway 1", "specific action or takeaway 2", "specific action or takeaway 3"],
  "category": "one of: Work, Learning, Entertainment, News, Ideas",
  "tags": ["tag1", "tag2", "tag3"],
  "relevance": 3
}}

Category guidelines:
- Work: professional, career, business, productivity tools
- Learning: tutorials, how-tos, educational, skills
- Entertainment: fun, humor, interesting, culture
- News: current events, announcements, updates
- Ideas: concepts, strategy, frameworks, inspiration"""

    try:
        body = json.dumps({
            "model": MODEL,
            "max_tokens": 2000,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()

        req = urllib.request.Request(
            LM_STUDIO_URL,
            data=body,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())

        text = result["choices"][0]["message"]["content"]
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        return json.loads(text.strip())
    except Exception as e:
        return {
            "title": url[:60],
            "summary": f"Could not analyze: {e}",
            "category": "Ideas",
            "tags": [],
            "relevance": 3
        }


def build_html(items):
    items_json = json.dumps(items).replace("</", r"<\/")
    count = len(items)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Content Digest</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Montserrat', -apple-system, system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ color: #ff6b35; margin-bottom: 4px; font-size: 24px; }}
  .subtitle {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
  .filters {{ position: sticky; top: 0; background: #1a1a2e; padding: 12px 0; border-bottom: 1px solid #333; z-index: 10; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .filters button {{ padding: 6px 14px; border: 1px solid #444; border-radius: 16px; background: transparent; color: #ccc; cursor: pointer; font-size: 13px; transition: all 0.2s; }}
  .filters button:hover {{ border-color: #ff6b35; color: #ff6b35; }}
  .filters button.active {{ background: #ff6b35; border-color: #ff6b35; color: white; }}
  .filters select {{ padding: 6px 10px; border: 1px solid #444; border-radius: 8px; background: #16213e; color: #ccc; font-size: 13px; margin-left: auto; }}
  .item {{ background: #16213e; padding: 15px; margin: 12px 0; border-radius: 8px; border-left: 3px solid #ff6b35; position: relative; }}
  .item h3 {{ color: #e0e0e0; font-size: 15px; padding-right: 30px; margin-bottom: 6px; }}
  .item h3 a {{ color: #e0e0e0; text-decoration: none; }}
  .item h3 a:hover {{ color: #4ecdc4; }}
  .meta {{ color: #888; font-size: 12px; margin: 4px 0 8px; }}
  .summary {{ color: #ccc; font-size: 14px; line-height: 1.6; margin-bottom: 16px; }}
  .action-points {{ margin-top: 16px; margin-bottom: 12px; }}
  .tags {{ margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }}
  .tag {{ padding: 2px 8px; background: #333; color: #aaa; border-radius: 10px; font-size: 11px; }}
  .cat-tag {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; background: #333; color: #aaa; margin-right: 6px; }}
  .dismiss {{ position: absolute; top: 12px; right: 12px; width: 26px; height: 26px; border: none; border-radius: 50%; background: transparent; color: #666; cursor: pointer; font-size: 16px; transition: all 0.2s; }}
  .dismiss:hover {{ background: #ff4444; color: white; }}
  .empty {{ text-align: center; color: #666; margin-top: 60px; }}
  .empty p {{ font-size: 18px; margin-bottom: 8px; }}
</style>
</head>
<body>
<h1>Content Digest</h1>
<p class="subtitle"><span id="count">{count}</span> items saved</p>
<div class="filters">
  <button class="active" data-cat="all">All</button>
  <button data-cat="Work">Work</button>
  <button data-cat="Learning">Learning</button>
  <button data-cat="Entertainment">Entertainment</button>
  <button data-cat="News">News</button>
  <button data-cat="Ideas">Ideas</button>
  <select id="sort-select">
    <option value="date">Sort: Newest</option>
    <option value="relevance">Sort: Relevance</option>
  </select>
</div>
<div id="items-container"></div>
<div class="empty" id="empty-state" style="display:none">
  <p>No items yet</p>
  <span>Add URLs from the menu bar app to get started.</span>
</div>
<script>
const DATA = {items_json};
let currentFilter = "all", currentSort = "date";
function escapeHtml(s) {{ const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }}
function render() {{
  let items = [...DATA];
  if (currentFilter !== "all") items = items.filter(i => i.category === currentFilter);
  if (currentSort === "date") items.sort((a, b) => (b.saved_at || "").localeCompare(a.saved_at || ""));
  else items.sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
  const container = document.getElementById("items-container");
  const empty = document.getElementById("empty-state");
  if (items.length === 0) {{ container.innerHTML = ""; empty.style.display = "block"; return; }}
  empty.style.display = "none";
  container.innerHTML = items.map(item => {{
    const tags = (item.tags || []).map(t => `<span class="tag">${{escapeHtml(t)}}</span>`).join("");
    const date = item.saved_at ? new Date(item.saved_at).toLocaleDateString() : "";
    return `<div class="item" data-url="${{escapeHtml(item.url)}}">
      <button class="dismiss" onclick="dismissItem(this)" title="Remove">&times;</button>
      <h3><a href="${{item.url}}" target="_blank">${{escapeHtml(item.title)}}</a></h3>
      <div class="meta"><span class="cat-tag">${{item.category}}</span>${{date}}</div>
      <p class="summary">${{escapeHtml(item.summary)}}</p>
      ${{(item.action_points && item.action_points.length) ? `<div class="action-points"><strong style="color:#ff9f1c;font-size:13px;">Action Pointers</strong><ul style="margin-top:6px;padding-left:18px;color:#ccc;font-size:13px;line-height:1.8">${{item.action_points.map(a => `<li>${{escapeHtml(a)}}</li>`).join("")}}</ul></div>` : ""}}
      <div class="tags">${{tags}}</div>
    </div>`;
  }}).join("");
}}
function dismissItem(btn) {{
  const card = btn.closest(".item");
  const idx = DATA.findIndex(i => i.url === card.dataset.url);
  if (idx !== -1) DATA.splice(idx, 1);
  card.remove();
  document.getElementById("count").textContent = DATA.length;
  if (DATA.length === 0) document.getElementById("empty-state").style.display = "block";
}}
document.querySelectorAll(".filters button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".filters button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.cat;
    render();
  }});
}});
document.getElementById("sort-select").addEventListener("change", e => {{ currentSort = e.target.value; render(); }});
render();
</script>
</body>
</html>"""


class ContentDigestApp(rumps.App):
    def __init__(self):
        super().__init__("📌", quit_button=None)
        self.menu = [
            rumps.MenuItem("Add URL...", callback=self.add_url),
            rumps.MenuItem("View Knowledge Base", callback=self.view_kb),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]
        self.is_processing = False

    def add_url(self, _):
        if self.is_processing:
            rumps.alert("Please wait", "Already processing a URL.")
            return
        import subprocess
        script = '''tell application "System Events"
            activate
            set userInput to text returned of (display dialog "Paste a URL to save and summarize:" default answer "https://" with title "Content Digest" buttons {"Cancel", "Save"} default button "Save")
        end tell
        return userInput'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode != 0:
            return
        url = result.stdout.strip()
        if True:
            if not url.startswith(("http://", "https://")):
                rumps.alert("Invalid URL", "Please enter a valid URL starting with http:// or https://")
                return
            self.is_processing = True
            self.title = "⏳"
            threading.Thread(target=self._process_url, args=(url,), daemon=True).start()

    def _process_url(self, url):
        try:
            content = fetch_url_content(url)
            if content is None:
                rumps.notification("Content Digest", "Could not fetch", f"Unable to extract content from {url[:60]}")
                return
            analysis = analyze_with_lmstudio(url, content)
            data = _load_data()
            if url in [i["url"] for i in data["items"]]:
                rumps.notification("Content Digest", "Already saved", url[:60])
                return
            item = {
                "url": url,
                "title": analysis.get("title", url[:60]),
                "summary": analysis.get("summary", "No summary available"),
                "action_points": analysis.get("action_points", []),
                "category": analysis.get("category", "Ideas"),
                "tags": analysis.get("tags", []),
                "relevance": analysis.get("relevance", 3),
                "saved_at": datetime.now().isoformat(),
            }
            data["items"].insert(0, item)
            _save_data(data)
            HTML_FILE.write_text(build_html(data["items"]))
            rumps.notification(
                "Content Digest",
                f"Saved: {item['title']}",
                f"{item['category']} — {item['summary'][:80]}"
            )
        except Exception as e:
            rumps.notification("Content Digest", "Error", str(e))
        finally:
            self.is_processing = False
            self.title = "📌"

    @rumps.notifications
    def notification_center(self, info):
        self.view_kb(None)

    def view_kb(self, _):
        data = _load_data()
        HTML_FILE.write_text(build_html(data["items"]))
        webbrowser.open(f"file://{HTML_FILE}")

    def quit_app(self, _):
        rumps.quit_application()


class ReceiverHandler(BaseHTTPRequestHandler):
    def __init__(self, app_instance, *args, **kwargs):
        self.app_instance = app_instance
        super().__init__(*args, **kwargs)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        url = body.get("url", "").strip()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())
        if url.startswith(("http://", "https://")):
            self.app_instance.title = "⏳"
            self.app_instance.is_processing = True
            threading.Thread(target=self.app_instance._process_url, args=(url,), daemon=True).start()

    def log_message(self, format, *args):
        pass


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "localhost"
    finally:
        s.close()


if __name__ == "__main__":
    BASE_DIR.mkdir(exist_ok=True)
    app = ContentDigestApp()
    local_ip = get_local_ip()
    print(f"[receiver] Listening on http://{local_ip}:7778/add")

    def start_receiver():
        handler = lambda *args, **kwargs: ReceiverHandler(app, *args, **kwargs)
        server = HTTPServer(("0.0.0.0", 7778), handler)
        server.serve_forever()

    threading.Thread(target=start_receiver, daemon=True).start()
    app.run()
