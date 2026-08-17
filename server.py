#!/usr/bin/env python3
"""Content Digest Server -- headless, always-on URL processor."""

import hmac
import json
import math
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone, timedelta
import fcntl
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Anchor to this file's directory, like daily_brief.py, so the server and the
# brief always agree on where runtime data lives regardless of machine.
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from extractors import get_extractor, normalize_url
from daily_brief import pick_resurfaced  # one scorer for brief and deck

DATA_FILE = BASE_DIR / "knowledge.json"
FAILURES_FILE = BASE_DIR / "failures.json"
HTML_FILE = BASE_DIR / "knowledge.html"
INBOX_FILE = BASE_DIR / "inbox.json"
EMB_FILE = BASE_DIR / "embeddings.json"

# Brand lockup for the /view header; falls back to plain text if missing.
LOGO_SVG = ""
try:
    LOGO_SVG = (BASE_DIR / "design" / "logo" / "content-digest-lockup-horizontal-dark.svg").read_text()
except Exception:
    pass

VALID_CATEGORIES = {"Work", "Learning", "Entertainment", "News", "Ideas"}
VALID_STATES = {"act", "revisit", "archive", ""}
RETRY_INTERVAL_HOURS = 6
MAX_AUTO_RETRIES = 3

# Auto-archive decay (feature 3): untouched items age out of the active view.
# News goes stale fastest; everything else gets three weeks. An item the brief
# has resurfaced RESURFACE_STRIKES times with no response archives regardless
# of age. Reversible: archived is a filter away, and the brief reports counts.
RESURFACE_FILE = BASE_DIR / "resurface.json"
DECAY_TTL_DAYS = {"News": 7}
DECAY_TTL_DEFAULT_DAYS = 21
RESURFACE_STRIKES = 3

# ---------------------------------------------------------------------------
# Content quality gates. Three layers, because each one has caught real junk:
#   1. _blocked_url_reason: placeholder domains, localhost, private IPs
#      (the KB once saved its own /view page and example.com).
#   2. _junk_content_reason: interstitial / authwall / proxy-error text that
#      arrives with HTTP 200 and a non-empty body (lnkd.in redirect pages,
#      r.jina.ai "request timed out" bodies).
#   3. _junk_analysis_reason: last line of defense on the MODEL OUTPUT, for
#      junk phrasings that slip past 1 and 2.
# A page that fails any layer becomes a recorded failure (visible, retryable),
# never a saved item.
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = {"example.com", "example.org", "example.net", "localhost", "test.com"}

_PRIVATE_IP_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|0\.0\.0\.0|169\.254\."
    r"|172\.(1[6-9]|2\d|3[01])\."          # 172.16/12
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)"  # 100.64/10 CGNAT incl. Tailscale
)

_JUNK_CONTENT_MARKERS = (
    "checking your browser before accessing",
    "check your browser before accessing",
    "you're being redirected",
    "you are being redirected",
    "if you are not redirected",
    "if you're not redirected",
    "click here if you are not automatically redirected",
    "redirecting you to",
    "enable javascript and cookies",
    "please enable javascript",
    "agree & join linkedin",
    "sign in to view",
    "join now to see",
    "verify you are human",
    "complete the security check",
    "attention required! | cloudflare",
    "just a moment...",
    "access to this page has been denied",
    "request timed out",
    "err_timed_out",
    "warning: target url returned error",
    "this domain is for use in illustrative examples",
    "this domain is established to be used for illustrative examples",
)

# Substring markers: junk wherever they appear in a title.
_JUNK_TITLE_MARKERS = (
    "untitled", "short title", "no title", "access check", "access warning",
    "agree & join", "browser verification", "browser check", "security check",
    "page not found", "just a moment", "lnkd.in",
)
# Exact-title markers: junk only when they ARE the whole title.
_JUNK_TITLE_EXACT = ("learn more", "redirect", "error", "error page", "sign in", "home")

_JUNK_SUMMARY_MARKERS = (
    "does not contain any substantive content",
    "appears to be an experimental placeholder",
    "check your browser",
    "being redirected",
    "redirection page",
    "before accessing",
    "agreeing to the platform's terms",
    "this article is empty",
    "no content could be extracted",
)


def _blocked_url_reason(url):
    """Reject URLs that can never be real content."""
    try:
        import urllib.parse as _up
        host = _up.urlsplit(url).hostname or ""
    except Exception:
        return None
    host = host.lower()
    bare = host[4:] if host.startswith("www.") else host
    if bare in _BLOCKED_HOSTS:
        return f"Placeholder/test domain: {bare}"
    if _PRIVATE_IP_RE.match(bare) or bare.endswith(".local"):
        return f"Local/private address: {bare}"
    return None


def _junk_content_reason(text):
    """Detect interstitial, authwall, and proxy-error bodies that arrive as
    HTTP 200. Real articles mentioning these phrases are long; junk pages are
    short, so markers only reject when the body is small."""
    if not text:
        return "Empty content"
    t = text.strip()
    if len(t) < 200:
        return f"Content too short ({len(t)} chars)"
    words = t.split()
    if len(words) < 40:
        return f"Content too short ({len(words)} words)"
    if len(set(w.lower() for w in words)) < 20:
        return "Content is repetitive boilerplate"
    low = t.lower()
    if len(t) < 2500:
        for marker in _JUNK_CONTENT_MARKERS:
            if marker in low:
                return f"Interstitial/error page detected: '{marker}'"
    return None


def _junk_analysis_reason(analysis):
    """Final gate on the model output before anything is saved."""
    if analysis.get("unusable"):
        return f"Model flagged content unusable: {str(analysis.get('reason', ''))[:120]}"
    title = str(analysis.get("title", "")).strip().lower()
    if title in _JUNK_TITLE_EXACT:
        return f"Junk title detected: '{title[:60]}'"
    for marker in _JUNK_TITLE_MARKERS:
        if marker in title and len(title) < 60:
            return f"Junk title detected: '{title[:60]}'"
    summary = str(analysis.get("summary", "")).strip().lower()
    for marker in _JUNK_SUMMARY_MARKERS:
        if marker in summary:
            return f"Junk summary detected: '{marker}'"
    return None

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
OLLAMA_MODEL = "qwen2.5:3b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_SECRETS = json.loads(Path(BASE_DIR / "secrets.json").read_text())
GROQ_API_KEY = _SECRETS.get("groq_api_key", "")
GROQ_MODEL = "llama-3.1-8b-instant"  # llama3-8b-8192 decommissioned by Groq (verified 2026-07-19)

AUTH_TOKEN = _SECRETS.get("auth_token", "")
if AUTH_TOKEN in ("", "NEW_TOKEN", "YOUR_TOKEN_HERE"):
    # A known placeholder is treated as no token at all: better to reject
    # everything loudly than to run production auth on a guessable string.
    AUTH_TOKEN = ""
    print("[server] WARNING: auth_token is missing or a placeholder in secrets.json; "
          "all authenticated endpoints will reject requests until a real token is set.")

COOKIE_NAME = "cd_session"


def _session_cookie_value():
    """Cookie value derived from the token: proves knowledge of the secret
    without ever placing the bearer token itself in browser storage."""
    return hmac.new(AUTH_TOKEN.encode(), b"content-digest-cookie-v1", "sha256").hexdigest()


# Trusted source ranges: loopback, RFC1918 private, and the 100.64/10 CGNAT
# block Tailscale uses. Anything else (a port-forward, a public interface)
# is refused outright, before auth is even considered.
_TRUSTED_SOURCE_RE = re.compile(
    r"^(127\.|10\.|192\.168\."
    r"|172\.(1[6-9]|2\d|3[01])\."
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)"
)


def _trusted_source(ip):
    return ip == "::1" or bool(_TRUSTED_SOURCE_RE.match(ip))

is_processing = False
data_lock = threading.Lock()


def _load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"items": []}


def _save_data(data):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(DATA_FILE)


def fetch_url_content(url):
    import urllib.request
    ua = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}
    # Source-aware extractors first (Reddit, YouTube, X). Reddit is exclusive:
    # the generic path is known-blocked (direct fetch 403s, jina IPs banned),
    # so falling through would only waste two timeouts.
    extractor, exclusive = get_extractor(url)
    if extractor:
        try:
            text = extractor(url)
        except Exception as e:
            print(f'[fetch] extractor error: {type(e).__name__}: {e}')
            text = None
        if text:
            return text
        if exclusive:
            return None
        print('[fetch] extractor empty; falling back to generic path')
    # Primary: direct fetch + trafilatura extraction
    try:
        import trafilatura
        req = urllib.request.Request(url, headers=ua)
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if text:
            return text[:3000]
        print('[fetch] direct extract empty; trying reader proxy')
    except Exception as e:
        print(f'[fetch error] direct: {e}; trying reader proxy')
    # Fallback: reader proxy for sites that block direct fetch.
    # NOTE: the proxy returns error bodies ("request timed out") with HTTP 200,
    # so its output must pass the junk gate, not just a length check.
    try:
        req = urllib.request.Request('https://r.jina.ai/' + url, headers=ua)
        with urllib.request.urlopen(req, timeout=30) as r:
            md = r.read().decode('utf-8', errors='ignore')
        if md and len(md.strip()) > 300 and not _junk_content_reason(md.strip()[:3000]):
            print('[fetch] reader proxy succeeded')
            return md[:3000]
        print('[fetch] reader proxy returned too little or junk')
    except Exception as e:
        print(f'[fetch error] reader proxy: {e}')
    return None


def _build_prompt(url, content):
    return f"""Analyze this saved article or post. Return ONLY a JSON object, no other text, no markdown.

URL: {url}
Content: {content[:2000]}

FIRST, decide if this is real content. If the text is a login wall, a "checking your browser" or redirect notice, a CAPTCHA page, an error message, a cookie banner, or an empty placeholder rather than an actual article or post, return exactly:
{{"unusable": true, "reason": "one short sentence why"}}

Otherwise return exactly this JSON:
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
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "content-digest/0.4",  # Groq 403s the default Python-urllib UA
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


def validate_analysis(analysis, url):
    """Enforce the JSON contract before anything touches storage."""
    if not isinstance(analysis, dict):
        raise ValueError("AI response is not a JSON object")
    clean = {}
    title = analysis.get("title")
    clean["title"] = str(title).strip()[:120] if title else url[:60]
    summary = analysis.get("summary")
    clean["summary"] = str(summary).strip()[:2000] if summary else "No summary available"
    aps = analysis.get("action_points")
    clean["action_points"] = [str(a).strip()[:300] for a in aps if str(a).strip()][:5] if isinstance(aps, list) else []
    cat = str(analysis.get("category", "")).strip().title()
    clean["category"] = cat if cat in VALID_CATEGORIES else "Ideas"
    tags = analysis.get("tags")
    clean["tags"] = [str(t).strip()[:40] for t in tags if str(t).strip()][:6] if isinstance(tags, list) else []
    try:
        clean["relevance"] = max(1, min(5, int(analysis.get("relevance", 3))))
    except (TypeError, ValueError):
        clean["relevance"] = 3
    return clean


# ---------------------------------------------------------------------------
# Semantic search: local embeddings via Ollama, cosine retrieval, ask endpoint
# ---------------------------------------------------------------------------

emb_lock = threading.Lock()


def _load_embeddings():
    if EMB_FILE.exists():
        try:
            return json.loads(EMB_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_embeddings(embs):
    tmp = EMB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(embs))
    tmp.rename(EMB_FILE)


def embed_text(text):
    """Return an embedding vector via local Ollama, or None (graceful skip)."""
    try:
        body = json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text[:2000]}).encode()
        req = urllib.request.Request(
            OLLAMA_EMBED_URL, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            vec = json.loads(resp.read().decode()).get("embedding")
        return vec if vec else None
    except Exception as e:
        print(f"[embed] unavailable ({type(e).__name__}); skipping")
        return None


def _item_embed_source(item):
    return f"{item.get('title', '')}\n{item.get('summary', '')}\n{' '.join(item.get('tags', []))}"


def embed_item(item):
    vec = embed_text(_item_embed_source(item))
    if vec is None:
        return
    with emb_lock:
        embs = _load_embeddings()
        embs[item["url"]] = vec
        _save_embeddings(embs)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def backfill_embeddings():
    """Embed any saved items that do not have vectors yet. Runs at startup."""
    embs = _load_embeddings()
    items = _load_data()["items"]
    missing = [i for i in items if i["url"] not in embs]
    if not missing:
        return
    print(f"[embed] Backfilling {len(missing)} item(s)")
    done = 0
    for item in missing:
        vec = embed_text(_item_embed_source(item))
        if vec is None:
            print("[embed] Backfill aborted: embedding endpoint unavailable")
            return
        with emb_lock:
            embs = _load_embeddings()
            embs[item["url"]] = vec
            _save_embeddings(embs)
        done += 1
    print(f"[embed] Backfilled {done} item(s)")


def answer_question(question):
    """Retrieve the most relevant saved items and answer from them."""
    qvec = embed_text(question)
    items = _load_data()["items"]
    scored = []
    if qvec:
        embs = _load_embeddings()
        for item in items:
            vec = embs.get(item["url"])
            if vec:
                scored.append((_cosine(qvec, vec), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [i for _, i in scored[:6]]
    else:
        # Degraded mode: keyword match when no embedding model is available
        q = question.lower()
        words = [w for w in re.split(r"\W+", q) if len(w) > 2]
        def kw_score(i):
            hay = f"{i.get('title','')} {i.get('summary','')} {' '.join(i.get('tags', []))}".lower()
            return sum(1 for w in words if w in hay)
        ranked = sorted(items, key=kw_score, reverse=True)
        top = [i for i in ranked[:6] if kw_score(i) > 0]
    if not top:
        return {"answer": "Nothing in your knowledge base matches that question yet.", "sources": []}
    context = "\n\n".join(
        f"[{n+1}] {i['title']}\nSummary: {i['summary']}\nURL: {i['url']}"
        for n, i in enumerate(top))
    prompt = f"""You are the user's personal knowledge base assistant. Answer the question using ONLY the saved items below. Be concise and specific. Cite items as [1], [2] etc. If the items do not contain the answer, say so plainly.

Question: {question}

Saved items:
{context}

Answer:"""
    try:
        answer = _try_ollama(prompt)
    except Exception:
        try:
            answer = _try_groq(prompt)
        except Exception:
            return {"answer": "AI endpoints are unavailable right now. Here are the closest matches instead.",
                    "sources": [{"title": i["title"], "url": i["url"]} for i in top]}
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
    return {"answer": answer[:3000],
            "sources": [{"title": i["title"], "url": i["url"]} for i in top]}




def _load_failures():
    if not FAILURES_FILE.exists():
        return {"items": []}
    with open(FAILURES_FILE, "r") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _save_failures(data):
    with open(FAILURES_FILE, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _record_inbox(url):
    now = datetime.now(timezone(timedelta(hours=4))).isoformat()
    try:
        inbox = json.loads(INBOX_FILE.read_text()) if INBOX_FILE.exists() else {"items": []}
    except Exception:
        inbox = {"items": []}
    inbox["items"].insert(0, {"url": url, "received_at": now})
    tmp = INBOX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(inbox, indent=2))
    tmp.rename(INBOX_FILE)
    print("[inbox] Captured: " + url[:60])


def _record_failure(url, error_type, error_reason):
    now = datetime.now(timezone(timedelta(hours=4))).isoformat()
    failures = _load_failures()
    existing = next((f for f in failures["items"] if f["url"] == url), None)
    if existing:
        existing["last_failed_at"] = now
        existing["retry_count"] = existing.get("retry_count", 0) + 1
        existing["error_type"] = error_type
        existing["error_reason"] = error_reason
    else:
        failures["items"].insert(0, {
            "url": url,
            "first_failed_at": now,
            "last_failed_at": now,
            "retry_count": 0,
            "error_type": error_type,
            "error_reason": error_reason,
        })
    _save_failures(failures)
    print("[failure] Recorded " + error_type + ": " + url[:60])


def _remove_failure(url):
    failures = _load_failures()
    before = len(failures["items"])
    failures["items"] = [f for f in failures["items"] if f["url"] != url]
    if len(failures["items"]) < before:
        _save_failures(failures)


def _self_heal_failures():
    data = _load_data()
    saved_urls = {i["url"] for i in data["items"]}
    failures = _load_failures()
    before = len(failures["items"])
    failures["items"] = [f for f in failures["items"] if f["url"] not in saved_urls]
    removed = before - len(failures["items"])
    if removed > 0:
        _save_failures(failures)
        print("[startup] Self-healed " + str(removed) + " stale failure(s)")


def process_url(url, content=None):
    """Process one URL end to end. If content is provided (browser-side capture
    from the Chrome extension), the fetch step is skipped entirely."""
    global is_processing
    try:
        is_processing = True
        url = normalize_url(url)
        blocked = _blocked_url_reason(url)
        if blocked:
            _record_failure(url, "quality", blocked)
            print(f"[reject] {blocked}: {url[:60]}")
            return {"status": "failed", "error_type": "quality", "reason": blocked}
        data = _load_data()
        if url in [i["url"] for i in data["items"]]:
            print(f"[skip] Already saved: {url[:60]}")
            _remove_failure(url)
            return {"status": "already_saved", "url": url}
        if content:
            content = str(content).strip()[:3000]
            print(f"[fetch] Using browser-captured content ({len(content)} chars)")
            junk = _junk_content_reason(content)
            if junk:
                print(f"[fetch] Browser content rejected ({junk}); refetching server-side")
                content = None
        if not content:
            try:
                content = fetch_url_content(url)
                if content is None:
                    _record_failure(url, "fetch", "Could not fetch URL content")
                    print(f"[error] Could not fetch: {url[:60]}")
                    return {"status": "failed", "error_type": "fetch", "reason": "Could not fetch URL content"}
            except Exception as e:
                _record_failure(url, "fetch", f"{type(e).__name__}: {str(e)[:200]}")
                print(f"[error] Fetch failed: {e}")
                return {"status": "failed", "error_type": "fetch", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
        # Junk gate: interstitials, authwalls, and proxy-error bodies must
        # become visible failures, never summarized items.
        junk = _junk_content_reason(content)
        if junk:
            _record_failure(url, "quality", junk)
            print(f"[reject] {junk}: {url[:60]}")
            return {"status": "failed", "error_type": "quality", "reason": junk}
        try:
            raw_analysis = analyze_with_ai(url, content)
        except Exception as e:
            _record_failure(url, "ai", f"{type(e).__name__}: {str(e)[:200]}")
            print(f"[error] AI failed: {e}")
            return {"status": "failed", "error_type": "ai", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
        # Model-output gate: the model may flag unusable content, and junk
        # titles/summaries that slipped through are caught here.
        junk = _junk_analysis_reason(raw_analysis if isinstance(raw_analysis, dict) else {})
        if junk:
            _record_failure(url, "quality", junk)
            print(f"[reject] {junk}: {url[:60]}")
            return {"status": "failed", "error_type": "quality", "reason": junk}
        try:
            analysis = validate_analysis(raw_analysis, url)
        except Exception as e:
            _record_failure(url, "ai", f"{type(e).__name__}: {str(e)[:200]}")
            print(f"[error] AI validation failed: {e}")
            return {"status": "failed", "error_type": "ai", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
        try:
            item = {
                "url": url,
                "title": analysis["title"],
                "summary": analysis["summary"],
                "action_points": analysis["action_points"],
                "category": analysis["category"],
                "tags": analysis["tags"],
                "relevance": analysis["relevance"],
                "state": "",
                "saved_at": datetime.now(timezone(timedelta(hours=4))).isoformat(),
            }
            with data_lock:
                fresh = _load_data()
                if url not in [i["url"] for i in fresh["items"]]:
                    fresh["items"].insert(0, item)
                    _save_data(fresh)
            _remove_failure(url)
            HTML_FILE.write_text(build_html(_load_data()["items"]))
            threading.Thread(target=embed_item, args=(item,), daemon=True).start()
            print(f"[saved] {item['title']} ({item['category']})")
            return {"status": "saved", "title": item["title"], "category": item["category"]}
        except Exception as e:
            _record_failure(url, "storage", f"{type(e).__name__}: {str(e)[:200]}")
            print(f"[error] Storage failed: {e}")
            return {"status": "failed", "error_type": "storage", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        is_processing = False


DECK_MAX = 10
resurface_lock = threading.Lock()


def _load_resurface():
    try:
        return json.loads(RESURFACE_FILE.read_text()) if RESURFACE_FILE.exists() else {}
    except Exception:
        return {}


def get_deck(limit=DECK_MAX):
    """Triage deck contents: same scorer and fatigue ledger as the brief, so
    items the 07:00 brief resurfaced today are on cooldown and never reappear
    in the same day's deck."""
    now = datetime.now(timezone(timedelta(hours=4)))
    return pick_resurfaced(_load_data()["items"], _load_resurface(), now, limit=limit)


def record_deck_skip(url):
    """A skipped deck card counts as a resurfacing with no response: it stamps
    the cooldown (tomorrow's brief will not repeat it) and adds a strike
    toward auto-archive."""
    now = datetime.now(timezone(timedelta(hours=4)))
    with resurface_lock:
        resurface = _load_resurface()
        r = resurface.setdefault(url, {"count": 0})
        r["count"] = r.get("count", 0) + 1
        r["last"] = now.isoformat()
        tmp = RESURFACE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(resurface, indent=2))
        tmp.rename(RESURFACE_FILE)


def _sign_triage(url, state, expires):
    """HMAC signature for one-tap triage links in the daily brief.
    daily_brief.py carries the mirror implementation; keep them identical."""
    msg = f"{url}|{state}|{expires}".encode()
    return hmac.new(AUTH_TOKEN.encode(), b"triage-v1:" + msg, "sha256").hexdigest()


def decay_sweep():
    """Feature 3: auto-archive untouched items past their TTL, and items the
    brief resurfaced RESURFACE_STRIKES times with no response. Runs at startup
    and every retry cycle. Sets auto_archived_at so the brief can report it."""
    now = datetime.now(timezone(timedelta(hours=4)))
    try:
        resurface = json.loads(RESURFACE_FILE.read_text()) if RESURFACE_FILE.exists() else {}
    except Exception:
        resurface = {}
    archived = 0
    with data_lock:
        data = _load_data()
        for item in data["items"]:
            if item.get("state"):
                continue
            reason = None
            if resurface.get(item["url"], {}).get("count", 0) >= RESURFACE_STRIKES:
                reason = "resurfaced without response"
            else:
                try:
                    saved = datetime.fromisoformat(item.get("saved_at", ""))
                except (ValueError, TypeError):
                    continue
                if saved.tzinfo is None:
                    saved = saved.replace(tzinfo=timezone(timedelta(hours=4)))
                ttl = DECAY_TTL_DAYS.get(item.get("category"), DECAY_TTL_DEFAULT_DAYS)
                if (now - saved).days >= ttl:
                    reason = f"untouched past {ttl}d TTL"
            if reason:
                item["state"] = "archive"
                item["auto_archived_at"] = now.isoformat()
                archived += 1
        if archived:
            _save_data(data)
            HTML_FILE.write_text(build_html(data["items"]))
    if archived:
        print(f"[decay] Auto-archived {archived} item(s)")
    return archived


def set_item_state(url, state):
    """Set act / revisit / archive on a saved item."""
    if state not in VALID_STATES:
        return False
    with data_lock:
        data = _load_data()
        found = False
        for item in data["items"]:
            if item["url"] == url:
                item["state"] = state
                found = True
                break
        if found:
            _save_data(data)
            HTML_FILE.write_text(build_html(data["items"]))
    return found


# ---------------------------------------------------------------------------
# Self-healing capture: auto-retry failures, reconcile the inbox
# ---------------------------------------------------------------------------

def _reconcile_inbox():
    """Queue inbox URLs that never became items or failures (dropped requests)."""
    try:
        inbox = json.loads(INBOX_FILE.read_text()) if INBOX_FILE.exists() else {"items": []}
    except Exception:
        return []
    saved = {i["url"] for i in _load_data()["items"]}
    failed = {f["url"] for f in _load_failures()["items"]}
    cutoff = datetime.now(timezone(timedelta(hours=4))) - timedelta(minutes=30)
    orphans = []
    for entry in inbox["items"]:
        raw = entry.get("url", "")
        url = normalize_url(raw)
        if not url or url in saved or url in failed or raw in saved or raw in failed:
            continue
        try:
            received = datetime.fromisoformat(entry.get("received_at", ""))
        except ValueError:
            continue
        if received < cutoff and url not in orphans:
            orphans.append(url)
    return orphans[:10]


def retry_loop():
    """Every RETRY_INTERVAL_HOURS: retry fetch failures (max MAX_AUTO_RETRIES)
    and re-queue orphaned inbox URLs. Makes capture fire-and-forget."""
    while True:
        time.sleep(RETRY_INTERVAL_HOURS * 3600)
        try:
            decay_sweep()
            retryable = [
                f["url"] for f in _load_failures()["items"]
                if f.get("error_type") == "fetch" and f.get("retry_count", 0) < MAX_AUTO_RETRIES
            ][:10]
            orphans = _reconcile_inbox()
            queue = retryable + [u for u in orphans if u not in retryable]
            if queue:
                print(f"[retry] Sweep: {len(retryable)} failure(s), {len(orphans)} inbox orphan(s)")
            for url in queue:
                process_url(url)
                time.sleep(20)
        except Exception as e:
            print(f"[retry] Sweep error: {type(e).__name__}: {e}")


def build_html(items, failures=None, deck_urls=None):
    if failures is None:
        failures = _load_failures().get("items", [])
    if deck_urls is None:
        deck_urls = []
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Content Digest</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Content Digest">
<meta name="theme-color" content="#1a1a2e">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Montserrat', -apple-system, system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ color: #ff6b35; margin-bottom: 4px; font-size: 24px; }}
  h1.brand {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
  h1.brand svg {{ height: 34px; width: auto; display: block; }}
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
  .filters button.failed-btn {{ border-color: #c83232; color: #ff6b6b; }}
  .filters button.failed-btn.active {{ background: #c83232; color: #fff; border-color: #c83232; }}
  .failure-card {{ background: #2a1a1a; border-left: 4px solid #c83232; padding: 16px; border-radius: 8px; margin-bottom: 12px; }}
  .failure-card .url {{ color: #ff9f1c; word-break: break-all; font-size: 13px; margin-bottom: 8px; }}
  .failure-card .meta {{ color: #888; font-size: 12px; margin-bottom: 8px; }}
  .failure-card .reason {{ color: #ff6b6b; font-size: 12px; margin-bottom: 12px; background: #1a0e0e; padding: 8px; border-radius: 4px; font-family: monospace; word-break: break-word; }}
  .failure-card .actions {{ display: flex; gap: 8px; }}
  .failure-card button {{ background: #1e1e1e; border: 1px solid #444; color: #ccc; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; font-family: 'Montserrat', sans-serif; }}
  .failure-card button.retry-btn {{ border-color: #ff9f1c; color: #ff9f1c; }}
  .failure-card button.retry-btn:hover {{ background: #ff9f1c; color: #000; }}
  .failure-card button.delete-btn:hover {{ background: #c83232; color: #fff; border-color: #c83232; }}
  .badge-fetch {{ background: #c83232; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }}
  .badge-ai {{ background: #c87a32; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }}
  .badge-storage {{ background: #6b32c8; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }}
  .badge-quality {{ background: #b8860b; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }}
  .state-row {{ display: flex; gap: 6px; margin-top: 12px; }}
  .state-row button {{ background: #1e1e1e; border: 1px solid #333; color: #888; padding: 4px 12px; border-radius: 14px; cursor: pointer; font-size: 11px; font-family: 'Montserrat', sans-serif; }}
  .state-row button.st-act.on {{ background: #c83232; color: #fff; border-color: #c83232; font-weight: 600; }}
  .state-row button.st-revisit.on {{ background: #3B82F6; color: #fff; border-color: #3B82F6; font-weight: 600; }}
  .state-row button.st-archive.on {{ background: #444; color: #ddd; border-color: #555; font-weight: 600; }}
  .item.archived {{ opacity: 0.55; }}
  .state-pill {{ padding: 2px 8px; border-radius: 10px; font-size: 10px; margin-right: 8px; text-transform: uppercase; font-weight: 600; }}
  .state-pill.act {{ background: #c83232; color: #fff; }}
  .state-pill.revisit {{ background: #3B82F6; color: #fff; }}
  .state-pill.archive {{ background: #444; color: #ccc; }}
  .ask-row {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .ask-row input {{ flex: 1; background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; padding: 9px 14px; border-radius: 10px; font-size: 13px; outline: none; font-family: 'Montserrat', sans-serif; }}
  .ask-row input:focus {{ border-color: #ff6b35; }}
  .ask-row button {{ background: #ff6b35; border: none; color: #000; padding: 9px 18px; border-radius: 10px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: 'Montserrat', sans-serif; }}
  .ask-row button:disabled {{ opacity: 0.5; cursor: wait; }}
  #review-btn {{ background: #1e1e1e; border: 1px solid #ff6b35; color: #ff6b35; padding: 6px 14px; border-radius: 20px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: 'Montserrat', sans-serif; }}
  #review-btn:hover {{ background: #ff6b35; color: #000; }}
  .deck-overlay {{ display: none; position: fixed; inset: 0; background: rgba(10,10,20,0.96); z-index: 100; align-items: center; justify-content: center; padding: 16px; }}
  .deck-card {{ background: #16213e; border: 1px solid #2a3a5e; border-radius: 16px; padding: 24px; max-width: 560px; width: 100%; max-height: 82vh; overflow-y: auto; }}
  .deck-top {{ display: flex; justify-content: space-between; align-items: center; color: #888; font-size: 13px; margin-bottom: 14px; }}
  .deck-close {{ background: none; border: none; color: #555; font-size: 22px; cursor: pointer; line-height: 1; }}
  .deck-close:hover {{ color: #ff4444; }}
  .deck-actions {{ display: flex; gap: 8px; margin-top: 18px; flex-wrap: wrap; }}
  .deck-actions button {{ flex: 1; min-width: 96px; padding: 13px 0; border-radius: 10px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; font-family: 'Montserrat', sans-serif; }}
  .deck-act {{ background: #c83232; color: #fff; }}
  .deck-later {{ background: #3B82F6; color: #fff; }}
  .deck-archive {{ background: #4B5563; color: #fff; }}
  .deck-skip {{ background: #1e1e1e; color: #888; border: 1px solid #333 !important; }}
  .deck-key {{ color: #555; font-size: 11px; margin-top: 12px; text-align: center; }}
  .deck-done {{ text-align: center; padding: 26px 10px; }}
  #ask-answer {{ display: none; background: #16213e; border: 1px solid #2a3a5e; border-radius: 12px; padding: 16px; margin-bottom: 18px; font-size: 13px; line-height: 1.7; color: #cbd5e1; white-space: pre-wrap; }}
  #ask-answer .ask-sources {{ margin-top: 10px; font-size: 12px; }}
  #ask-answer .ask-sources a {{ color: #ff9f1c; text-decoration: none; display: block; margin-top: 4px; }}
  #ask-answer .ask-close {{ float: right; background: none; border: none; color: #555; font-size: 16px; cursor: pointer; }}
</style>
</head>
<body>
<h1 class="brand">{LOGO_SVG if LOGO_SVG else 'Content Digest'} <span id="count"></span></h1>
<div class="ask-row">
  <input type="text" id="ask-input" placeholder="Ask your knowledge base... (e.g. what did I save about Kubernetes?)">
  <button id="ask-btn">Ask</button>
</div>
<div id="ask-answer"></div>
<div class="filters">
  <button class="active" data-cat="All">All</button>
  <button data-cat="Work">Work</button>
  <button data-cat="Learning">Learning</button>
  <button data-cat="News">News</button>
  <button data-cat="Ideas">Ideas</button>
  <button data-cat="Entertainment">Entertainment</button>
  <button data-cat="Failed" class="failed-btn">Failed ({len(failures)})</button>
  <select id="state-select">
    <option value="active">Active (default)</option>
    <option value="act">Act on this</option>
    <option value="revisit">Revisit later</option>
    <option value="archive">Archived</option>
    <option value="all">Everything</option>
  </select>
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
  <button id="review-btn" style="display:none" onclick="openDeck()">Review</button>
</div>
<div class="deck-overlay" id="deck-overlay"><div class="deck-card" id="deck-card"></div></div>
<div id="items-container"></div>
<div id="empty-state" style="display:none">No items saved yet. Add a URL to get started.</div>
<script>
var DATA = {json.dumps(items)};
var FAILURES = {json.dumps(failures)};
var DECK = {json.dumps(deck_urls)};
var currentFilter = "All";
var currentSort = "newest";
var currentSearch = "";
var currentState = "active";
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
  if (currentFilter === "Failed") {{
    var failContainer = document.getElementById("items-container");
    var failEmpty = document.getElementById("empty-state");
    document.getElementById("count").textContent = "(" + FAILURES.length + ")";
    if (FAILURES.length === 0) {{
      failContainer.innerHTML = "";
      failEmpty.textContent = "No failed URLs. Everything you have shared has been processed successfully.";
      failEmpty.style.display = "block";
      return;
    }}
    failEmpty.style.display = "none";
    var filtered = FAILURES.filter(f => {{
      if (!q) return true;
      return (f.url || "").toLowerCase().includes(q) ||
             (f.error_reason || "").toLowerCase().includes(q);
    }});
    if (filtered.length === 0) {{
      failContainer.innerHTML = "";
      failEmpty.textContent = "No failures match: " + q;
      failEmpty.style.display = "block";
      return;
    }}
    failContainer.innerHTML = filtered.map(f => {{
      var firstDate = formatDate(f.first_failed_at);
      var lastDate = formatDate(f.last_failed_at);
      var retryNote = (f.retry_count > 0) ? " | Retried " + f.retry_count + " time(s)" : "";
      var badgeClass = "badge-" + (f.error_type || "fetch");
      return `<div class="failure-card" data-url="${{escapeHtml(f.url)}}">
        <div class="meta"><span class="${{badgeClass}}">${{escapeHtml(f.error_type || "unknown")}}</span> &nbsp; First failed: ${{firstDate}}${{retryNote}}</div>
        <div class="url"><a href="${{f.url}}" target="_blank" style="color:#ff9f1c;">${{escapeHtml(f.url)}}</a></div>
        <div class="reason">${{escapeHtml(f.error_reason || "No reason recorded")}}</div>
        <div class="actions">
          <button class="retry-btn" onclick="retryFailure(this)">Retry</button>
          <button class="delete-btn" onclick="deleteFailure(this)">Delete</button>
        </div>
      </div>`;
    }}).join("");
    return;
  }}
  var items = DATA.filter(i => {{
    if (currentFilter !== "All" && i.category !== currentFilter) return false;
    var st = i.state || "";
    if (currentState === "active" && st === "archive") return false;
    if (currentState === "act" && st !== "act") return false;
    if (currentState === "revisit" && st !== "revisit") return false;
    if (currentState === "archive" && st !== "archive") return false;
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
    const st = item.state || "";
    const statePill = st ? `<span class="state-pill ${{st}}">${{st === "act" ? "act on this" : st === "revisit" ? "revisit later" : "archived"}}</span>` : "";
    const stateBtns = `<div class="state-row">
        <button class="st-act${{st === "act" ? " on" : ""}}" onclick="setState(this, 'act')">Act</button>
        <button class="st-revisit${{st === "revisit" ? " on" : ""}}" onclick="setState(this, 'revisit')">Later</button>
        <button class="st-archive${{st === "archive" ? " on" : ""}}" onclick="setState(this, 'archive')">Archive</button>
      </div>`;
    return `<div class="item${{st === "archive" ? " archived" : ""}}" data-url="${{escapeHtml(item.url)}}">
      <button class="dismiss" onclick="dismissItem(this)" title="Remove">&times;</button>
      <h3><a href="${{item.url}}" target="_blank">${{escapeHtml(item.title)}}</a></h3>
      <div class="meta">${{statePill}}<span class="cat-tag">${{item.category}}</span>${{date}}</div>
      <p class="summary">${{escapeHtml(item.summary)}}</p>
      ${{(item.action_points && item.action_points.length) ? `<div class="action-points"><strong style="color:#ff9f1c;font-size:13px;">Action Pointers</strong><ul style="margin-top:6px;padding-left:18px;color:#ccc;font-size:13px;line-height:1.8">${{item.action_points.map(a => `<li>${{escapeHtml(a)}}</li>`).join("")}}</ul></div>` : ""}}
      <div class="tags">${{tags}}</div>
      ${{stateBtns}}
    </div>`;
  }}).join("");
}}
function setState(btn, state) {{
  var card = btn.closest(".item");
  var url = card.dataset.url;
  var item = DATA.find(i => i.url === url);
  var newState = (item && item.state === state) ? "" : state;
  if (item) item.state = newState;
  fetch("/state", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{url: url, state: newState}})
  }}).catch(e => console.warn("State sync failed:", e));
  render();
}}
function askKB() {{
  var input = document.getElementById("ask-input");
  var btn = document.getElementById("ask-btn");
  var panel = document.getElementById("ask-answer");
  var q = input.value.trim();
  if (!q) return;
  btn.disabled = true;
  btn.textContent = "Thinking...";
  panel.style.display = "block";
  panel.textContent = "Searching your knowledge base...";
  fetch("/ask", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{question: q}})
  }}).then(r => r.json()).then(res => {{
    var src = (res.sources || []).map(s => `<a href="${{s.url}}" target="_blank">&#8594; ${{escapeHtml(s.title)}}</a>`).join("");
    panel.innerHTML = `<button class="ask-close" onclick="this.parentElement.style.display='none'">&times;</button>` +
      escapeHtml(res.answer || "No answer.") +
      (src ? `<div class="ask-sources"><strong style="color:#ff9f1c;">Sources</strong>${{src}}</div>` : "");
  }}).catch(e => {{
    panel.textContent = "Ask failed: " + e;
  }}).finally(() => {{
    btn.disabled = false;
    btn.textContent = "Ask";
  }});
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
function retryFailure(btn) {{
  var card = btn.closest(".failure-card");
  var url = card.dataset.url;
  btn.textContent = "Retrying...";
  btn.disabled = true;
  fetch("/retry", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{url: url}})
  }}).then(() => {{
    setTimeout(() => {{ window.location.reload(); }}, 4000);
  }}).catch(e => {{
    btn.textContent = "Retry";
    btn.disabled = false;
    console.warn("Retry failed:", e);
  }});
}}
function deleteFailure(btn) {{
  var card = btn.closest(".failure-card");
  var url = card.dataset.url;
  var idx = FAILURES.findIndex(f => f.url === url);
  if (idx !== -1) FAILURES.splice(idx, 1);
  card.remove();
  var failBtn = document.querySelector(".filters button.failed-btn");
  if (failBtn) failBtn.textContent = "Failed (" + FAILURES.length + ")";
  if (currentFilter === "Failed") document.getElementById("count").textContent = "(" + FAILURES.length + ")";
  fetch("/failures/delete", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{url: url}})
  }}).catch(e => console.warn("Failure delete sync failed:", e));
}}
// --- Triage deck: one card at a time over the same scorer as the brief ---
var deckPos = 0, deckTriaged = 0, deckSkipped = 0;
function deckCurrent() {{
  while (deckPos < DECK.length) {{
    var it = DATA.find(i => i.url === DECK[deckPos]);
    if (it && it.state !== "archive") return it;
    deckPos++;
  }}
  return null;
}}
function openDeck() {{
  deckPos = 0; deckTriaged = 0; deckSkipped = 0;
  if (document.activeElement) document.activeElement.blur();
  document.getElementById("deck-overlay").style.display = "flex";
  renderDeck();
}}
function closeDeck() {{
  document.getElementById("deck-overlay").style.display = "none";
  render();
}}
function renderDeck() {{
  var card = document.getElementById("deck-card");
  var it = deckCurrent();
  if (!it) {{
    card.innerHTML = `<div class="deck-done">
      <div style="font-size:36px;color:#ff9f1c;">&#10003;</div>
      <h3 style="margin:10px 0;color:#fff;">Deck clear</h3>
      <p style="color:#9CA3AF;font-size:14px;">${{deckTriaged}} triaged, ${{deckSkipped}} skipped. Nothing left to review today.</p>
      <button style="margin-top:18px;padding:11px 26px;border:none;border-radius:10px;background:#ff6b35;color:#000;font-weight:600;font-size:14px;cursor:pointer;font-family:'Montserrat',sans-serif;" onclick="closeDeck()">Done</button>
    </div>`;
    return;
  }}
  var ap = (it.action_points && it.action_points.length)
    ? `<div style="margin-top:10px;"><strong style="color:#ff9f1c;font-size:13px;">Action Pointers</strong><ul style="margin-top:6px;padding-left:18px;color:#ccc;font-size:13px;line-height:1.8">${{it.action_points.map(a => `<li>${{escapeHtml(a)}}</li>`).join("")}}</ul></div>`
    : "";
  card.innerHTML = `
    <div class="deck-top"><span>${{deckPos + 1}} of ${{DECK.length}} &nbsp;&middot;&nbsp; ${{DECK.length - deckPos - 1}} remaining</span><button class="deck-close" onclick="closeDeck()" title="Close">&times;</button></div>
    <h3 style="font-size:17px;margin-bottom:6px;"><a href="${{it.url}}" target="_blank" style="color:#fff;text-decoration:none;">${{escapeHtml(it.title)}}</a></h3>
    <div class="meta"><span class="cat-tag">${{it.category}}</span>${{formatDate(it.saved_at)}}</div>
    <p class="summary">${{escapeHtml(it.summary)}}</p>
    ${{ap}}
    <div class="deck-actions">
      <button class="deck-act" onclick="deckResolve('act')">Act</button>
      <button class="deck-later" onclick="deckResolve('revisit')">Later</button>
      <button class="deck-archive" onclick="deckResolve('archive')">Archive</button>
      <button class="deck-skip" onclick="deckResolve('skip')">Skip</button>
    </div>
    <div class="deck-key">a act &nbsp;&middot;&nbsp; l later &nbsp;&middot;&nbsp; x archive &nbsp;&middot;&nbsp; space skip &nbsp;&middot;&nbsp; esc close</div>`;
}}
function deckResolve(action) {{
  var it = deckCurrent();
  if (!it) return;
  if (action === "skip") {{
    deckSkipped++;
    fetch("/deck/skip", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{url: it.url}})
    }}).catch(e => console.warn("Skip sync failed:", e));
  }} else {{
    it.state = action;
    deckTriaged++;
    fetch("/state", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{url: it.url, state: action}})
    }}).catch(e => console.warn("State sync failed:", e));
  }}
  deckPos++;
  renderDeck();
}}
document.addEventListener("keydown", e => {{
  if (document.getElementById("deck-overlay").style.display !== "flex") return;
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
  if (e.key === "Escape") {{ closeDeck(); return; }}
  if (!deckCurrent() && (e.key === " " || e.key === "Enter")) {{ e.preventDefault(); closeDeck(); return; }}
  if (e.key === "a") deckResolve("act");
  else if (e.key === "l") deckResolve("revisit");
  else if (e.key === "x") deckResolve("archive");
  else if (e.key === " ") {{ e.preventDefault(); deckResolve("skip"); }}
}});
if (DECK.length > 0) {{
  var rb = document.getElementById("review-btn");
  rb.style.display = "";
  rb.textContent = "Review (" + DECK.length + ")";
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
document.getElementById("state-select").addEventListener("change", e => {{ currentState = e.target.value; render(); }});
document.getElementById("ask-btn").addEventListener("click", askKB);
document.getElementById("ask-input").addEventListener("keydown", e => {{ if (e.key === "Enter") askKB(); }});
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


LOCKED_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Content Digest</title></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,sans-serif;padding:40px;max-width:600px;margin:0 auto;">
<h2 style="color:#ff6b35;">Locked</h2>
<p>This knowledge base requires a one-time unlock per device.</p>
<p style="color:#888;font-size:14px;">Paste the auth token from secrets.json. A session cookie
keeps this device signed in afterwards; the token itself is not stored.</p>
<!-- GET form to /view?token=... so installed PWAs (own cookie jar, no address
     bar) can unlock themselves without leaving the app. -->
<form method="GET" action="/view" style="display:flex;gap:8px;margin-top:16px;">
  <input type="password" name="token" placeholder="Auth token" autocomplete="off"
         style="flex:1;background:#1e1e1e;border:1px solid #333;color:#e0e0e0;padding:10px 14px;border-radius:10px;font-size:14px;outline:none;">
  <button type="submit"
          style="background:#ff6b35;border:none;color:#000;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">Unlock</button>
</form>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _bearer_ok(self):
        auth = self.headers.get("Authorization", "")
        return bool(AUTH_TOKEN) and hmac.compare_digest(
            auth.encode(), f"Bearer {AUTH_TOKEN}".encode())

    def _cookie_ok(self):
        if not AUTH_TOKEN:
            return False
        expected = _session_cookie_value().encode()
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, val = part.strip().partition("=")
            if name == COOKIE_NAME and val and hmac.compare_digest(val.encode(), expected):
                return True
        return False

    def _authed(self):
        return self._bearer_ok() or self._cookie_ok()

    def _deny(self, code=401, msg="Unauthorized"):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": False, "error": msg}).encode())

    def do_GET(self):
        if not _trusted_source(self.client_address[0]):
            self._deny(403, "Forbidden source")
            return
        path, _, query = self.path.partition("?")
        if path == "/triage":
            # One-tap state links from the daily brief. The HMAC signature IS
            # the credential (no cookie needed: mail clients have none), the
            # expiry bounds replay, and the trusted-source guard above still
            # applies, so links only work from the tailnet or home LAN.
            import urllib.parse as _up
            q = _up.parse_qs(query)
            url = q.get("u", [""])[0]
            state = q.get("s", [""])[0]
            sig = q.get("sig", [""])[0]
            try:
                expires = int(q.get("e", ["0"])[0])
            except ValueError:
                expires = 0
            code, msg = 200, ""
            labels = {"act": "Act on this", "revisit": "Revisit later", "archive": "Archived"}
            if not (AUTH_TOKEN and url and state in ("act", "revisit", "archive")):
                code, msg = 400, "Invalid link."
            elif time.time() > expires:
                code, msg = 410, "This link has expired. Triage links are valid for 72 hours; use tomorrow's brief."
            elif not hmac.compare_digest(sig.encode(), _sign_triage(url, state, expires).encode()):
                code, msg = 403, "Invalid link signature."
            elif not set_item_state(url, state):
                code, msg = 404, "Item not found. It may have been deleted or merged."
            if code == 200:
                msg = f"Done: marked <b style='color:#ff9f1c;'>{labels[state]}</b>."
            self.send_response(code)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write((
                "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                "<title>Content Digest</title></head>"
                "<body style='background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,sans-serif;"
                "padding:40px;max-width:600px;margin:0 auto;'>"
                f"<h2 style='color:#ff6b35;'>Content Digest</h2><p>{msg}</p>"
                "<p style='color:#666;font-size:13px;'>You can close this tab.</p>"
                "</body></html>").encode())
            return
        if path == "/view":
            if not self._cookie_ok():
                import urllib.parse as _up
                supplied = _up.parse_qs(query).get("token", [""])[0]
                if AUTH_TOKEN and hmac.compare_digest(supplied.encode(), AUTH_TOKEN.encode()):
                    self.send_response(302)
                    self.send_header("Location", "/view")
                    self.send_header(
                        "Set-Cookie",
                        f"{COOKIE_NAME}={_session_cookie_value()}; Path=/; "
                        f"Max-Age=31536000; HttpOnly; SameSite=Lax")
                    self.end_headers()
                    return
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(LOCKED_HTML.encode())
                return
            try:
                html = build_html(_load_data()["items"],
                                  deck_urls=[i["url"] for i in get_deck()])
                HTML_FILE.write_text(html)
            except Exception as e:
                print(f"[view] Rebuild failed ({e}), serving cached")
                html = HTML_FILE.read_text() if HTML_FILE.exists() else "<html><body style='background:#1a1a2e;color:#e0e0e0;font-family:sans-serif;padding:40px'>Content Digest is temporarily unavailable. Try again shortly.</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            return
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "processing": is_processing}).encode())
            return
        if path == "/failures":
            if not self._authed():
                self._deny()
                return
            failures = _load_failures()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(failures).encode())
            return
        if path == "/manifest.webmanifest":
            manifest = {
                "name": "Content Digest",
                "short_name": "Digest",
                "start_url": "/view",
                "scope": "/",
                "display": "standalone",
                "background_color": "#1a1a2e",
                "theme_color": "#1a1a2e",
                "icons": [
                    {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
                    {"src": "/assets/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.end_headers()
            self.wfile.write(json.dumps(manifest).encode())
            return
        if path.startswith("/assets/"):
            asset_dir = (BASE_DIR / "design" / "web").resolve()
            target = (asset_dir / path[len("/assets/"):]).resolve()
            ctypes = {".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
            if target.parent == asset_dir and target.is_file() and target.suffix in ctypes:
                self.send_response(200)
                self.send_header("Content-Type", ctypes[target.suffix])
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
            self.send_response(404)
            self.end_headers()
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
        if not _trusted_source(self.client_address[0]):
            self._deny(403, "Forbidden source")
            return

        # Read the body FIRST so the URL is captured before auth or fetch can fail.
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            body = {}

        is_ingest = self.path not in ("/delete", "/retry", "/failures/delete", "/state", "/ask", "/deck/skip")

        # Durable inbox capture: record every incoming link before auth and fetch.
        if is_ingest:
            _inbox_url = body.get("url", "").strip()
            if _inbox_url:
                _record_inbox(_inbox_url)

        # Auth gate runs AFTER capture, so a rejected link is still recorded.
        # EVERY POST endpoint requires auth: bearer token (clients) or the
        # session cookie (the /view UI). Mutating endpoints were previously
        # exempt; that exemption was the core of issue #2.
        if not self._authed():
            self._deny()
            return

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

        if self.path == "/failures/delete":
            url = body.get("url", "").strip()
            if url:
                _remove_failure(url)
                HTML_FILE.write_text(build_html(_load_data()["items"]))
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/retry":
            url = body.get("url", "").strip()
            self.wfile.write(json.dumps({"ok": True}).encode())
            if url.startswith(("http://", "https://")):
                threading.Thread(target=process_url, args=(url,), daemon=True).start()
            return

        if self.path == "/state":
            url = body.get("url", "").strip()
            state = body.get("state", "").strip().lower()
            ok = set_item_state(url, state)
            self.wfile.write(json.dumps({"ok": ok}).encode())
            return

        if self.path == "/deck/skip":
            url = body.get("url", "").strip()
            if url:
                record_deck_skip(url)
            self.wfile.write(json.dumps({"ok": bool(url)}).encode())
            return

        if self.path == "/ask":
            question = str(body.get("question", "")).strip()[:500]
            if not question:
                self.wfile.write(json.dumps({"answer": "Ask a question about your saved items.", "sources": []}).encode())
                return
            result = answer_question(question)
            self.wfile.write(json.dumps(result).encode())
            return

        if self.path == "/add_sync":
            url = body.get("url", "").strip()
            if not url.startswith(("http://", "https://")):
                self.wfile.write(json.dumps({"status": "invalid", "reason": "Not a valid URL"}).encode())
                return
            result = process_url(url, content=body.get("content"))
            if result is None:
                result = {"status": "unknown"}
            self.wfile.write(json.dumps(result).encode())
            return

        url = body.get("url", "").strip()
        self.wfile.write(json.dumps({"ok": True}).encode())
        if url.startswith(("http://", "https://")):
            threading.Thread(target=process_url, args=(url,), kwargs={"content": body.get("content")}, daemon=True).start()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    BASE_DIR.mkdir(exist_ok=True)
    _self_heal_failures()
    decay_sweep()
    threading.Thread(target=retry_loop, daemon=True).start()
    threading.Thread(target=backfill_embeddings, daemon=True).start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7778
    # ThreadingHTTPServer: a slow /ask or /add_sync must never block the
    # iPhone shortcut, the menu bar client, or the Chrome extension.
    print(f"[server] Content Digest server v0.4 starting on 0.0.0.0:{port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
