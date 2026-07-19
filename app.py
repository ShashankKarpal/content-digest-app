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

# AI endpoint config
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_settings import OLLAMA_URL
except ImportError:
    OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = "YOUR_GROQ_KEY_HERE"
GROQ_MODEL = "llama-3.1-8b-instant"  # llama3-8b-8192 decommissioned by Groq (verified 2026-07-19)

AUTH_TOKEN = "YOUR_TOKEN_HERE"


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


def _build_prompt(url, content):
    return f"""Analyze this saved article or post. Return ONLY a JSON object, no other text, no markdown.

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

CATEGORY DECISION RULES (apply in this order, stop at first match):

1. NEWS: published in the last 30 days AND reports on a specific event, announcement, product launch, funding round, acquisition, policy change, or industry development. Time-sensitive. If you would not save this to reference 6 months from now, it is News.

2. ENTERTAINMENT: primary purpose is enjoyment, not utility. Movies, TV, music, sports, games, humor, lifestyle, celebrity, food-for-fun, travel-for-fun. If the content has no actionable takeaway and you saved it for pleasure, it is Entertainment.

3. LEARNING: teaches a specific skill or explains how something works at a technical level. Tutorials, step-by-step guides, deep-dives into protocols, frameworks, languages, tools, scientific concepts, technical primers. Answers "how does X work" or "how do I do X".

4. IDEAS: opinion, essay, framework, mental model, philosophy, strategy thinking, perspective pieces, thought leadership without a step-by-step. Answers "how should I think about X".

5. WORK: ONLY use if the content is directly applicable to a specific professional workflow: sales tactics, GTM playbooks, B2B strategy, hiring, management, business operations, productivity workflows you would action this week.

Pick exactly one. When in doubt between two, pick the one LATER in this list (News > Entertainment > Learning > Ideas > Work)."""


def _parse_response(text):
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    think_match = re.search(r'</think>(.*)', text, re.DOTALL)
    if think_match:
        text = think_match.group(1).strip()
    return json.loads(text)


def _try_ollama(prompt):
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result["message"]["content"]


def _try_groq(prompt):
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1000
    }).encode()
    req = urllib.request.Request(
        GROQ_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "content-digest/0.4",  # Groq 403s the default Python-urllib UA
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def analyze_with_ai(url, content):
    prompt = _build_prompt(url, content)

    # Try M1 Ollama first
    try:
        text = _try_ollama(prompt)
        return _parse_response(text)
    except Exception as e:
        print(f"[ai] Ollama unavailable ({e}), falling back to Groq")

    # Fall back to Groq
    try:
        text = _try_groq(prompt)
        return _parse_response(text)
    except Exception as e:
        print(f"[ai] Groq also failed ({e})")
        raise Exception("All AI endpoints unavailable")


def build_html(items):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Content Digest</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Montserrat', -apple-system, system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ color: #ff6b35; margin-bottom: 4px; font-size: 24px; }}
  .filters {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }}
  .filters button {{ background: #1e1e1e; border: 1px solid #333; color: #aaa; padding: 6px 14px; border-radius: 20px; cursor: pointer; font-size: 13px; }}
  .filters button.active {{ background: #ff9f1c; color: #000; border-color: #ff9f1c; font-weight: 600; }}
  select {{ background: #1e1e1e; border: 1px solid #333; color: #aaa; padding: 6px 10px; border-radius: 8px; font-size: 13px; }}
  .item {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 18px; margin-bottom: 14px; position: relative; }}
  .item h3 {{ font-size: 15px; margin-bottom: 6px; }}
  .item h3 a {{ color: #fff; text-decoration: none; }}
  .item h3 a:hover {{ color: #ff9f1c; }}
  .meta {{ font-size: 12px; color: #666; margin-bottom: 8px; }}
  .cat-tag {{ background: #2a2a2a; color: #ff9f1c; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-right: 8px; }}
  .summary {{ font-size: 13px; color: #bbb; line-height: 1.6; margin-bottom: 10px; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .tag {{ background: #222; color: #888; padding: 2px 8px; border-radius: 8px; font-size: 11px; }}
  .dismiss {{ position: absolute; top: 12px; right: 12px; background: none; border: none; color: #555; font-size: 18px; cursor: pointer; line-height: 1; }}
  .dismiss:hover {{ color: #ff4444; }}
  #empty-state {{ text-align: center; color: #555; margin-top: 60px; font-size: 15px; }}
  #count {{ color: #666; font-size: 13px; margin-left: 8px; }}
</style>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
<h1>Content Digest <span id="count"></span></h1>
<div class="filters">
  <button class="active" data-cat="All">All</button>
  <button data-cat="Work">Work</button>
  <button data-cat="Learning">Learning</button>
  <button data-cat="News">News</button>
  <button data-cat="Ideas">Ideas</button>
  <button data-cat="Entertainment">Entertainment</button>
  <select id="sort-select">
    <option value="newest">Newest first</option>
    <option value="oldest">Oldest first</option>
    <option value="relevance">By relevance</option>
  </select>
</div>
<div id="items-container"></div>
<div id="empty-state" style="display:none">No items saved yet. Add a URL to get started.</div>
<script>
var DATA = {json.dumps(items)};
var currentFilter = "All";
var currentSort = "newest";
function escapeHtml(s) {{
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}
function render() {{
  var items = DATA.filter(i => currentFilter === "All" || i.category === currentFilter);
  if (currentSort === "newest") items = items.slice().sort((a,b) => new Date(b.saved_at) - new Date(a.saved_at));
  else if (currentSort === "oldest") items = items.slice().sort((a,b) => new Date(a.saved_at) - new Date(b.saved_at));
  else if (currentSort === "relevance") items = items.slice().sort((a,b) => (b.relevance||0) - (a.relevance||0));
  document.getElementById("count").textContent = "(" + items.length + ")";
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
  const url = card.dataset.url;
  const idx = DATA.findIndex(i => i.url === url);
  if (idx !== -1) DATA.splice(idx, 1);
  card.remove();
  document.getElementById("count").textContent = "(" + DATA.length + ")";
  if (DATA.length === 0) document.getElementById("empty-state").style.display = "block";
  fetch("http://localhost:7778/delete", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{url: url}})
  }}).catch(e => console.warn("Delete sync failed:", e));
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
            analysis = analyze_with_ai(url, content)
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path != "/delete":
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {AUTH_TOKEN}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "Unauthorized"}).encode())
                return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if self.path == "/delete":
            url = body.get("url", "").strip()
            if url:
                data = _load_data()
                data["items"] = [i for i in data["items"] if i["url"] != url]
                _save_data(data)
                HTML_FILE.write_text(build_html(data["items"]))
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        url = body.get("url", "").strip()
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
