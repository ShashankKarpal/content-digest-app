#!/usr/bin/env python3
"""Content Digest Server -- headless, always-on URL processor."""

import json
import re
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_DIR = Path.home() / "content-digest-app"
DATA_FILE = BASE_DIR / "knowledge.json"
HTML_FILE = BASE_DIR / "knowledge.html"

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = json.loads(Path(BASE_DIR / "secrets.json").read_text()).get("groq_api_key", "")
GROQ_MODEL = "llama3-8b-8192"

AUTH_TOKEN = "REMOVED"

is_processing = False


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
        import urllib.request
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if not text:
            return None
        return text[:3000]
    except Exception as e:
        print(f'[fetch error] {e}')
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

1. NEWS: published in the last 30 days AND reports on a specific event, announcement, product launch, funding round, acquisition, policy change, or industry development. Time-sensitive.

2. ENTERTAINMENT: primary purpose is enjoyment, not utility. Movies, TV, music, sports, games, humor, lifestyle, celebrity, food-for-fun, travel-for-fun.

3. LEARNING: teaches a specific skill or explains how something works at a technical level. Tutorials, step-by-step guides, deep-dives into protocols, frameworks, languages, tools, scientific concepts, technical primers.

4. IDEAS: opinion, essay, framework, mental model, philosophy, strategy thinking, perspective pieces, thought leadership without a step-by-step.

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
    with urllib.request.urlopen(req, timeout=120) as resp:
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
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def analyze_with_ai(url, content):
    prompt = _build_prompt(url, content)
    try:
        text = _try_ollama(prompt)
        print(f"[ai] Processed via Ollama: {url[:60]}")
        return _parse_response(text)
    except Exception as e:
        print(f"[ai] Ollama failed ({e}), trying Groq")
    try:
        text = _try_groq(prompt)
        print(f"[ai] Processed via Groq: {url[:60]}")
        return _parse_response(text)
    except Exception as e:
        print(f"[ai] Groq also failed ({e})")
        raise Exception("All AI endpoints unavailable")


def process_url(url):
    global is_processing
    try:
        is_processing = True
        content = fetch_url_content(url)
        if content is None:
            print(f"[error] Could not fetch: {url[:60]}")
            return
        analysis = analyze_with_ai(url, content)
        data = _load_data()
        if url in [i["url"] for i in data["items"]]:
            print(f"[skip] Already saved: {url[:60]}")
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
        print(f"[saved] {item['title']} ({item['category']})")
    except Exception as e:
        print(f"[error] {e}")
    finally:
        is_processing = False


def build_html(items):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Content Digest</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Montserrat', -apple-system, system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ color: #ff6b35; margin-bottom: 4px; font-size: 24px; }}
  .subtitle {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
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
  .search-row {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
  .search-wrap {{ position: relative; flex: 1; min-width: 180px; }}
  .search-wrap input {{ width: 100%; background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; padding: 7px 14px 7px 34px; border-radius: 20px; font-size: 13px; outline: none; font-family: 'Montserrat', -apple-system, sans-serif; }}
  .search-wrap input:focus {{ border-color: #ff9f1c; }}
  .search-icon {{ position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: #666; font-size: 13px; pointer-events: none; }}
  .search-clear {{ background: none; border: none; color: #555; font-size: 18px; cursor: pointer; padding: 0 4px; }}
  .search-clear:hover {{ color: #ff4444; }}
  .search-toggle {{ display: flex; gap: 4px; }}
  .search-toggle button {{ background: #1e1e1e; border: 1px solid #333; color: #aaa; padding: 6px 12px; border-radius: 20px; cursor: pointer; font-size: 12px; font-family: 'Montserrat', sans-serif; }}
  .search-toggle button.s-active {{ background: #2a2a2a; color: #ff9f1c; border-color: #ff9f1c; font-weight: 600; }}
</style>
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
<div class="search-row">
  <div class="search-wrap">
    <span class="search-icon">&#128269;</span>
    <input type="text" id="search-input" placeholder="Search articles...">
  </div>
  <button class="search-clear" id="search-clear" title="Clear">&times;</button>
  <div class="search-toggle">
    <button class="s-active" data-mode="all">All fields</button>
    <button data-mode="title">Title only</button>
  </div>
</div>
<div id="items-container"></div>
<div id="empty-state" style="display:none">No items saved yet. Add a URL to get started.</div>
<script>
var DATA = {json.dumps(items)};
var currentFilter = "All";
var currentSort = "newest";
var currentSearch = "";
var searchMode = "all";
var searchDebounce;
function escapeHtml(s) {{
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}
function formatDate(s) {{
  if (!s) return "";
  return s.substring(8,10) + "/" + s.substring(5,7) + "/" + s.substring(0,4) + " " + s.substring(11,13) + ":" + s.substring(14,16);
}}
function render() {{
  var q = currentSearch.toLowerCase().trim();
  var items = DATA.filter(i => {{
    if (currentFilter !== "All" && i.category !== currentFilter) return false;
    if (!q) return true;
    if (searchMode === "title") return (i.title || "").toLowerCase().includes(q);
    return (i.title || "").toLowerCase().includes(q) ||
           (i.summary || "").toLowerCase().includes(q) ||
           (i.category || "").toLowerCase().includes(q) ||
           (i.action_points || []).join(" ").toLowerCase().includes(q) ||
           (i.tags || []).join(" ").toLowerCase().includes(q);
  }});
  if (currentSort === "newest") items = items.slice().sort((a,b) => new Date(b.saved_at) - new Date(a.saved_at));
  else if (currentSort === "oldest") items = items.slice().sort((a,b) => new Date(a.saved_at) - new Date(b.saved_at));
  else if (currentSort === "relevance") items = items.slice().sort((a,b) => (b.relevance||0) - (a.relevance||0));
  document.getElementById("count").textContent = "(" + items.length + ")";
  const container = document.getElementById("items-container");
  const empty = document.getElementById("empty-state");
  if (items.length === 0) {{
    container.innerHTML = "";
    empty.textContent = q ? "No articles match: " + q : "No items saved yet. Add a URL to get started.";
    empty.style.display = "block";
    return;
  }}
  empty.style.display = "none";
  container.innerHTML = items.map(item => {{
    const tags = (item.tags || []).map(t => `<span class="tag">${{escapeHtml(t)}}</span>`).join("");
    const date = formatDate(item.saved_at);
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
  fetch("/delete", {{
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
document.getElementById("search-input").addEventListener("input", e => {{
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {{
    currentSearch = e.target.value;
    render();
  }}, 150);
}});
document.getElementById("search-clear").addEventListener("click", () => {{
  currentSearch = "";
  document.getElementById("search-input").value = "";
  render();
}});
document.querySelectorAll(".search-toggle button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".search-toggle button").forEach(b => b.classList.remove("s-active"));
    btn.classList.add("s-active");
    searchMode = btn.dataset.mode;
    render();
  }});
}});
render();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/view":
            if HTML_FILE.exists():
                html = HTML_FILE.read_text()
            else:
                data = _load_data()
                html = build_html(data["items"])
                HTML_FILE.write_text(html)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            return
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "processing": is_processing}).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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
            threading.Thread(target=process_url, args=(url,), daemon=True).start()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    BASE_DIR.mkdir(exist_ok=True)
    print("[server] Content Digest server starting on 0.0.0.0:7778")
    server = HTTPServer(("0.0.0.0", 7778), Handler)
    server.serve_forever()
