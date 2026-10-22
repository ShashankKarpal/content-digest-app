#!/usr/bin/env python3
"""Content Digest Server -- headless, always-on URL processor."""

import hmac
import ipaddress
import json
import math
import os
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
from extractors import get_extractor, normalize_url, artifact_urls, container_page_reason
from extractors import guarded_urlopen, is_short_link
from extractors import blocked_url_reason as _blocked_url_reason   # the SSRF guard

DATA_FILE = BASE_DIR / "knowledge.json"
FAILURES_FILE = BASE_DIR / "failures.json"
HTML_FILE = BASE_DIR / "knowledge.html"
INBOX_FILE = BASE_DIR / "inbox.json"
EMB_FILE = BASE_DIR / "embeddings.json"
DISMISSED_FILE = BASE_DIR / "dismissed.json"
DISMISSED_CAP = 1000

# Brand lockup for the /view header; falls back to plain text if missing.
LOGO_SVG = ""
try:
    LOGO_SVG = (BASE_DIR / "design" / "logo" / "content-digest-lockup-horizontal-dark.svg").read_text()
except Exception:
    pass

VALID_CATEGORIES = {"Work", "Learning", "Entertainment", "News", "Ideas", "Tool"}
RETRY_INTERVAL_HOURS = 6
RETRY_FIRST_SWEEP_SECONDS = 600
MAX_AUTO_RETRIES = 3

# Decision 14 (2026-09-30): one-at-a-time triage and resurfacing are retired
# (the brief's backlog items and signed links, the deck, the card-level
# Act / Later / Archive controls, the fatigue ledger, the weekly loop line),
# and auto-archive decay is off. migrations.py put back every item decay
# archived. The state fields already on items stay as history; resurface.json,
# triage_log.jsonl and loopcheck-history.txt stay on disk and are no longer
# written.

# D1 (2026-09-05): runtime watchdog. The server proves it is alive by writing
# heartbeat.json every HEARTBEAT_SECONDS, and records the last authenticated
# contact per client in clients.json (the X-Client header names the client;
# unauthenticated requests and /health polls never count). The brief and the
# menu bar client read these to tell a quiet week from a dead capture path.
SERVER_VERSION = "0.6"
# One timezone for every timestamp the server writes (the host runs in +04).
TZ = timezone(timedelta(hours=4))
STARTED_AT = datetime.now(TZ).isoformat()
HEARTBEAT_FILE = BASE_DIR / "heartbeat.json"
CLIENTS_FILE = BASE_DIR / "clients.json"
BRIEF_SENT_FILE = BASE_DIR / "brief_sent.json"   # written by daily_brief.py after each successful send
HEARTBEAT_SECONDS = 300
KNOWN_CLIENTS = {"mac-client", "extension", "shortcut", "view", "brief"}

# ---------------------------------------------------------------------------
# Content quality gates. Three layers, because each one has caught real junk:
#   1. _blocked_url_reason: placeholder domains, localhost, private IPs
#      (the KB once saved its own /view page and example.com). It lives in
#      extractors.py as blocked_url_reason since 2026-10, so the short-link
#      resolver there checks every redirect hop with the same guard.
#   2. _junk_content_reason: interstitial / authwall / proxy-error text that
#      arrives with HTTP 200 and a non-empty body (lnkd.in redirect pages,
#      r.jina.ai "request timed out" bodies).
#   3. _junk_analysis_reason: last line of defense on the MODEL OUTPUT, for
#      junk phrasings that slip past 1 and 2.
# A page that fails any layer becomes a recorded failure (visible, retryable),
# never a saved item.
# ---------------------------------------------------------------------------

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


MAX_FETCH_BYTES = 2_000_000    # cap on any remote body we read
MAX_BODY_BYTES = 1_000_000     # cap on a POST body (extension captures are <= 20k chars)

# POST paths whose feature was retired. Any POST path without a handler falls
# through to the add path at the end of do_POST (that keeps old capture
# clients working), so a retired path must be listed here: otherwise a button
# on an old cached page would turn its item URL into a new save (red team,
# 2026-10). A retired path answers 410 {"status": "retired"} and records nothing.
# /state and /deck/skip: the card-level triage buttons and the deck (decision 14).
RETIRED_POST_PATHS = frozenset({"/state", "/deck/skip"})


def _js(obj):
    """JSON for inlining inside a <script> block: json.dumps does not escape
    '</', so a title or URL containing '</script>' broke out of the script
    context (stored XSS, audit 2026-09-02)."""
    return json.dumps(obj).replace("</", "<\\/")


def _atomic_write_text(path, text):
    """Write through a temp file named for this file and this thread, then
    rename it into place. Every writer used with_suffix(".tmp"), which is
    knowledge.tmp for knowledge.json AND knowledge.html, so a page render
    racing a data write could rename the page over the knowledge base
    (review, 2026-10)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    tmp.rename(path)


def _write_html(text):
    """Atomic replace so a reader never sees a torn knowledge.html."""
    _atomic_write_text(HTML_FILE, text)


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
# Local models only (owner rule). The Groq cloud fallback was removed in
# 2026-10: with Ollama down it sent the page text to Groq even with an empty
# key. A secrets.json that still carries groq_api_key is simply not read.
_SECRETS = json.loads(Path(BASE_DIR / "secrets.json").read_text())

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


# Explicit bind (audit A8, 2026-09-05). By default the server still listens on
# 0.0.0.0 behind the source allowlist above. When the gitignored config.json
# carries "bind_addresses": ["127.0.0.1", "<private-network address>"], it
# listens on exactly those instead, one ThreadingHTTPServer per address, so a
# packet from any other interface is refused by the kernel before Python sees
# it. Shipped switched off: turning it on is a config edit on the host, and it
# drops home-LAN capture unless that address is listed too.
BIND_RETRY_SECONDS = 120   # a tailnet address may appear seconds after login
BIND_RETRY_DELAY = 5
CONFIG_FILE = BASE_DIR / "config.json"


def _bind_addresses_from_config():
    """The optional bind_addresses list from config.json; [] when absent."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    except Exception as e:
        print(f"[server] config.json unreadable ({type(e).__name__}); binding 0.0.0.0", flush=True)
        return []
    addrs = cfg.get("bind_addresses") or []
    if not isinstance(addrs, list):
        return []
    out = []
    for a in addrs:
        try:
            ipaddress.ip_address(str(a).strip())
            out.append(str(a).strip())
        except ValueError:
            print(f"[server] ignoring invalid bind address {a!r}", flush=True)
    return out


def _bind_servers(addresses, port, handler, retry_seconds=BIND_RETRY_SECONDS,
                  delay=BIND_RETRY_DELAY, server_cls=ThreadingHTTPServer, sleep=time.sleep):
    """Bind one server per address, retrying each for up to retry_seconds
    because an interface address can arrive after the LaunchAgent starts.
    Returns the servers that bound; an address that never binds is logged and
    skipped so the others still serve."""
    servers = []
    for addr in addresses:
        deadline = time.monotonic() + retry_seconds
        while True:
            try:
                servers.append(server_cls((addr, port), handler))
                break
            except OSError as e:
                if time.monotonic() >= deadline:
                    print(f"[server] could not bind {addr}:{port} after {retry_seconds}s: {e}", flush=True)
                    break
                sleep(delay)
    return servers

is_processing = False
data_lock = threading.Lock()


def _load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"items": []}


def _save_data(data):
    _atomic_write_text(DATA_FILE, json.dumps(data, indent=2))


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
        with guarded_urlopen(req, timeout=15) as r:   # every redirect checked before it is followed
            final = r.geturl() or url
            blocked = _blocked_url_reason(final, resolve=False) if final != url else None
            if blocked:
                raise ValueError(f"redirected to a blocked address ({blocked})")
            html = r.read(MAX_FETCH_BYTES).decode('utf-8', errors='ignore')
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
        with guarded_urlopen(req, timeout=30) as r:
            md = r.read(MAX_FETCH_BYTES).decode('utf-8', errors='ignore')
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
  "category": "one of: Tool, Work, Learning, Entertainment, News, Ideas",
  "tags": ["tag1", "tag2", "tag3"],
  "relevance": 3
}}

CATEGORY DECISION RULES (apply in this order, stop at first match):

1. TOOL: a tool, app, repo, extension or product someone built and linked. The post's main point is the thing itself: an open-source repo, a browser extension, an app, a plugin, a CLI, a product shown by its maker.

2. NEWS: published in the last 30 days AND reports on a specific event, announcement, product launch, funding round, acquisition, policy change, or industry development. Time-sensitive.

3. ENTERTAINMENT: primary purpose is enjoyment, not utility. Movies, TV, music, sports, games, humor, lifestyle, celebrity, food-for-fun, travel-for-fun.

4. LEARNING: teaches a specific skill or explains how something works at a technical level. Tutorials, step-by-step guides, deep-dives into protocols, frameworks, languages, tools, scientific concepts, technical primers.

5. IDEAS: opinion, essay, framework, mental model, philosophy, strategy thinking, perspective pieces, thought leadership without a step-by-step.

6. WORK: ONLY use if the content is directly applicable to a specific professional workflow: sales tactics, GTM playbooks, B2B strategy, hiring, management, business operations, productivity workflows you would action this week.

Pick exactly one. When in doubt between two, pick the one LATER in this list (Tool > News > Entertainment > Learning > Ideas > Work)."""


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


def analyze_with_ai(url, content):
    """Summarize with the local model. There is no other endpoint: when Ollama
    is down this raises, process_url records an "ai" failure, and the retry
    sweep tries again later. The page text never leaves the host."""
    prompt = _build_prompt(url, content)
    try:
        text = _try_ollama(prompt)
    except Exception as e:
        print(f"[ai] Ollama failed ({type(e).__name__}: {e})")
        raise
    print(f"[ai] Processed via Ollama: {url[:60]}")
    return _parse_response(text)


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
    _atomic_write_text(EMB_FILE, json.dumps(embs))


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
        return {"answer": "The local model is unavailable right now. Here are the closest matches instead.",
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


def _record_inbox(url, authed=False):
    """Durable capture log. `authed` records whether the request carried a
    valid credential: the reconcile sweep only re-queues authenticated
    entries, otherwise the pre-auth capture was an unauthenticated write path
    into the whole pipeline (audit 2026-09-02). Capped so a chatty peer
    cannot grow the file without bound."""
    now = datetime.now(TZ).isoformat()
    try:
        inbox = json.loads(INBOX_FILE.read_text()) if INBOX_FILE.exists() else {"items": []}
    except Exception:
        inbox = {"items": []}
    inbox["items"].insert(0, {"url": url, "received_at": now, "authed": bool(authed)})
    inbox["items"] = inbox["items"][:500]
    _atomic_write_text(INBOX_FILE, json.dumps(inbox, indent=2))
    print("[inbox] Captured: " + url[:60])


def _record_failure(url, error_type, error_reason):
    now = datetime.now(TZ).isoformat()
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


def _load_dismissed():
    try:
        d = json.loads(DISMISSED_FILE.read_text()) if DISMISSED_FILE.exists() else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _dismiss(url):
    """Remember that the owner deleted this link (a saved item or a failure),
    so the self-healing inbox sweep never brings it back. Without this, a
    deleted link that had an authenticated inbox entry became an "orphan" and
    _reconcile_inbox re-queued it within one sweep, which broke the v0.1 rule
    that a delete is persistent. Keyed by the raw and the normalized form,
    value = when. A later capture of the same link (a newer inbox entry) is
    still processed, because _reconcile_inbox compares the two times."""
    now = datetime.now(TZ).isoformat()
    d = _load_dismissed()
    keys = {url}
    try:
        keys.add(normalize_url(url))
    except Exception:
        pass
    for k in keys:
        if k:
            d[k] = now
    if len(d) > DISMISSED_CAP:
        d = dict(sorted(d.items(), key=lambda kv: kv[1])[-DISMISSED_CAP:])
    _atomic_write_text(DISMISSED_FILE, json.dumps(d, indent=2))


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


# Summary self-check (decision 14, red-teamed 2026-10): no second model pass
# (the host has 8 GB and the model already fills it). Every name and number
# in the summary must appear in the text it was made from; what does not is
# listed, never rewritten. Pure text work on bounded input, so it needs no
# timeout; it runs after the save and a failure never touches the save.
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:['’.-][A-Za-z0-9]+)*")
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?:;]['\")\]]*\s+|\n\s*(?:[-*•]\s*)?)$")
_COMMON_CAPITALS = {"i", "a", "an", "the", "this", "that", "these", "those", "it", "its", "in", "on",
                    "for", "and", "or", "but", "if", "as", "at", "by", "to", "of", "with", "from"}
# Generic acronyms a summary uses as plain words; not names of anyone or
# anything. Calibrated 2026-10-22 on 24 live items: "AI" alone made 4 of the
# 6 flags while naming nothing the source left out.
_GENERIC_ACRONYMS = {"ai", "api", "apis", "ui", "ux", "llm", "llms", "saas", "b2b", "b2c", "ceo", "cto",
                     "cfo", "hr", "faq", "diy", "pdf", "url", "urls", "gpu", "cpu", "os", "ios", "kpi", "roi"}
SUMMARY_CHECK_MISSING_MAX = 10


def check_summary(summary, source, now=None):
    """{at, ok, names, numbers, missing}: how many distinct names and numbers
    the summary holds, and which of them the source text does not contain.
    A name is a capitalized word or an acronym that does not open a sentence;
    a number has at least two digits (single digits are too often spelled
    out in the source). Matching ignores case, a possessive 's and a plural s."""
    summary = str(summary or "")[:2000]
    low = str(source or "")[:3000].lower()
    digits = re.sub(r"(?<=\d),(?=\d)", "", low)

    def present(token, hay):
        # A plural or a possessive without its apostrophe on either side
        # still counts ("Notion's" in the summary, "Notions" in the source).
        for t in (token, token[:-1] if token.endswith("s") and len(token) > 3 else None):
            if t and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"s?(?![a-z0-9])", hay):
                return True
        return False

    names, numbers, missing = [], [], []
    for m in _NAME_TOKEN_RE.finditer(summary):
        token = re.sub(r"['’]s$", "", m.group(0)).rstrip(".")
        opens_sentence = bool(_SENTENCE_START_RE.search(summary[:m.start()]))
        for i, word in enumerate(token.split("-")):   # "Electron-based" checks "Electron"
            if not any(c.isupper() for c in word) or len(word) < 2:
                continue
            if word.lower() in _COMMON_CAPITALS or word.lower() in _GENERIC_ACRONYMS:
                continue
            if i == 0 and opens_sentence and word[0].isupper() and word[1:].islower():
                continue   # a plain capitalized word opening a sentence or a bullet
            if word.lower() not in names:
                names.append(word.lower())
                if not present(word.lower(), low):
                    missing.append(word)
    for m in _NUMBER_TOKEN_RE.finditer(summary):
        num = m.group(0).replace(",", "").rstrip(".")
        if sum(c.isdigit() for c in num) < 2 or num in numbers:
            continue
        numbers.append(num)
        if not re.search(r"(?<![0-9.])" + re.escape(num) + r"(?![0-9])", digits):
            missing.append(m.group(0).rstrip(".,"))
    return {"at": (now or datetime.now(TZ)).isoformat(), "ok": not missing,
            "names": len(names), "numbers": len(numbers), "missing": missing[:SUMMARY_CHECK_MISSING_MAX]}


def _update_item(url, fields):
    """Merge fields into one saved item under the data lock. False when the
    item is gone (deleted while a background step was running)."""
    with data_lock:
        data = _load_data()
        for item in data["items"]:
            if item["url"] == url:
                item.update(fields)
                _save_data(data)
                return True
    return False


def enrich_item(url, content, summary=""):
    """Runs after the save, on its own thread, so it can never delay or fail
    one: summary_checked (the summary's names and numbers against the text it
    was made from) and artifact_urls (the links the post points to, short
    links resolved hop by hop through the SSRF guard). Each step that fails
    is skipped and logged; the other still lands."""
    fields = {}
    try:
        fields["summary_checked"] = check_summary(summary, content)
    except Exception as e:
        print(f"[enrich] summary check skipped: {type(e).__name__}: {e}")
    try:
        fields["artifact_urls"] = artifact_urls(content or "", own_url=url)
    except Exception as e:
        print(f"[enrich] links skipped: {type(e).__name__}: {e}")
    if fields and _update_item(url, fields):
        missing = len(fields.get("summary_checked", {}).get("missing", []))
        print(f"[enrich] {len(fields.get('artifact_urls', []))} artifact link(s), "
              f"{missing} summary term(s) not in the source: {url[:60]}")


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
        container = container_page_reason(url)
        if container:
            _record_failure(url, "quality", container)
            print(f"[reject] feed page, not a post: {url[:60]}")
            return {"status": "failed", "error_type": "quality", "reason": container}
        if is_short_link(url):
            # normalize_url follows a short link to its destination; one that
            # is still short could not be resolved safely, and fetching it
            # would hand its redirects to urllib. "fetch" lets the retry sweep
            # try again later.
            reason = "Short link could not be resolved to a safe address"
            _record_failure(url, "fetch", reason)
            print(f"[reject] {reason}: {url[:60]}")
            return {"status": "failed", "error_type": "fetch", "reason": reason}
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
                "saved_at": datetime.now(TZ).isoformat(),
            }
            with data_lock:
                fresh = _load_data()
                inserted = url not in [i["url"] for i in fresh["items"]]
                if inserted:
                    fresh["items"].insert(0, item)
                    _save_data(fresh)
            _remove_failure(url)
            if not inserted:
                # Another save of the same link finished first (a double tap,
                # a Retry during the sweep). Its own post-save steps describe
                # the stored item; this call's summary must not overwrite them.
                print(f"[skip] Saved meanwhile by another request: {url[:60]}")
                return {"status": "already_saved", "url": url}
            _write_html(build_html(_load_data()["items"]))
            threading.Thread(target=embed_item, args=(item,), daemon=True).start()
            threading.Thread(target=enrich_item, args=(url, content, item["summary"]), daemon=True).start()
            print(f"[saved] {item['title']} ({item['category']})")
            return {"status": "saved", "title": item["title"], "category": item["category"]}
        except Exception as e:
            _record_failure(url, "storage", f"{type(e).__name__}: {str(e)[:200]}")
            print(f"[error] Storage failed: {e}")
            return {"status": "failed", "error_type": "storage", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        is_processing = False


clients_lock = threading.Lock()


def _write_json_atomic(path, payload):
    _atomic_write_text(path, json.dumps(payload, indent=2))


def _load_clients():
    try:
        return json.loads(CLIENTS_FILE.read_text()) if CLIENTS_FILE.exists() else {}
    except Exception:
        return {}


def _touch_client(name):
    """Record an authenticated contact from `name` (an allowlisted X-Client
    value, else 'api'). Never raises."""
    name = name if name in KNOWN_CLIENTS else "api"
    now = datetime.now(TZ).isoformat()
    try:
        with clients_lock:
            clients = _load_clients()
            clients[name] = now
            _write_json_atomic(CLIENTS_FILE, clients)
    except Exception as e:
        print(f"[clients] write failed: {type(e).__name__}: {e}")


def heartbeat_loop():
    """Write heartbeat.json every HEARTBEAT_SECONDS. The file's own mtime is the
    liveness signal; the body carries what a watcher needs to name the process."""
    while True:
        try:
            _write_json_atomic(HEARTBEAT_FILE, {
                "at": datetime.now(TZ).isoformat(),
                "started_at": STARTED_AT, "version": SERVER_VERSION, "pid": os.getpid()})
        except Exception as e:
            print(f"[heartbeat] write failed: {type(e).__name__}: {e}")
        time.sleep(HEARTBEAT_SECONDS)


def health_snapshot():
    """The /health body: cheap, content-free, safe to poll every 15 minutes."""
    last_save = None
    try:
        for item in _load_data().get("items", []):
            ts = item.get("saved_at")
            if ts and (last_save is None or ts > last_save):
                last_save = ts
    except Exception:
        pass
    clients = _load_clients()
    last_contact = max(clients.values()) if clients else None
    try:
        failures = len(_load_failures().get("items", []))
    except Exception:
        failures = None
    try:
        brief_sent = json.loads(BRIEF_SENT_FILE.read_text()).get("at") if BRIEF_SENT_FILE.exists() else None
    except Exception:
        brief_sent = None
    return {"ok": True, "processing": is_processing, "version": SERVER_VERSION,
            "started_at": STARTED_AT, "last_save_at": last_save,
            "last_client_contact_at": last_contact, "clients": clients, "failures": failures,
            "last_brief_sent_at": brief_sent}


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
    dismissed = _load_dismissed()
    cutoff = datetime.now(TZ) - timedelta(minutes=30)
    orphans = []
    for entry in inbox["items"]:
        if not entry.get("authed"):
            continue   # never auto-process what an unauthenticated peer posted
        raw = entry.get("url", "")
        url = normalize_url(raw)
        if not url or url in saved or url in failed or raw in saved or raw in failed:
            continue
        try:
            received = datetime.fromisoformat(entry.get("received_at", ""))
        except ValueError:
            continue
        gone = dismissed.get(url) or dismissed.get(raw)
        if gone:
            try:
                if received <= datetime.fromisoformat(gone):
                    continue   # the owner deleted it after this capture
            except ValueError:
                continue
        if received < cutoff and url not in orphans:
            orphans.append(url)
    return orphans[:10]


def retry_loop():
    """First sweep RETRY_FIRST_SWEEP_SECONDS after start, then every
    RETRY_INTERVAL_HOURS: retry fetch failures (max MAX_AUTO_RETRIES) and
    re-queue orphaned inbox URLs. Makes capture fire-and-forget. The short
    first delay matters because every deploy restarts the server: with a 6 h
    first sleep, a day with three deploys never swept at all (2026-09-04)."""
    delay = RETRY_FIRST_SWEEP_SECONDS
    while True:
        time.sleep(delay)
        delay = RETRY_INTERVAL_HOURS * 3600
        try:
            retryable = [
                f["url"] for f in _load_failures()["items"]
                if f.get("error_type") in ("fetch", "ai") and f.get("retry_count", 0) < MAX_AUTO_RETRIES
            ][:10]
            orphans = _reconcile_inbox()
            queue = retryable + [u for u in orphans if u not in retryable]
            print(f"[retry] Sweep: {len(retryable)} failure(s), {len(orphans)} inbox orphan(s)", flush=True)
            for url in queue:
                process_url(url)
                time.sleep(20)
        except Exception as e:
            print(f"[retry] Sweep error: {type(e).__name__}: {e}")


def build_html(items, failures=None):
    if failures is None:
        failures = _load_failures().get("items", [])
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
  h1 {{ color: #b17e51; margin-bottom: 4px; font-size: 24px; }}
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
  .check-note {{ font-size: 11px; color: #b8860b; margin: -4px 0 10px 0; }}
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
  .ask-row {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .ask-row input {{ flex: 1; background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; padding: 9px 14px; border-radius: 10px; font-size: 13px; outline: none; font-family: 'Montserrat', sans-serif; }}
  .ask-row input:focus {{ border-color: #b17e51; }}
  .ask-row button {{ background: #b17e51; border: none; color: #000; padding: 9px 18px; border-radius: 10px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: 'Montserrat', sans-serif; }}
  .ask-row button:disabled {{ opacity: 0.5; cursor: wait; }}
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
  <button data-cat="Tool">Tool</button>
  <button data-cat="Failed" class="failed-btn">Failed ({len(failures)})</button>
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
var DATA = {_js(items)};
var FAILURES = {_js(failures)};
var currentFilter = "All";
var currentSort = "newest";
var currentSearch = "";
var searchMode = "all";
var searchDebounce;
function escapeHtml(s) {{
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}
function safeHref(u) {{
  // Only http(s) may become a link; anything else (javascript:, data:) is inert.
  return /^https?:[/][/]/i.test(String(u)) ? escapeHtml(u) : "#";
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
        <div class="url"><a href="${{safeHref(f.url)}}" target="_blank" rel="noopener" style="color:#ff9f1c;">${{escapeHtml(f.url)}}</a></div>
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
      <h3><a href="${{safeHref(item.url)}}" target="_blank" rel="noopener">${{escapeHtml(item.title)}}</a></h3>
      <div class="meta"><span class="cat-tag">${{escapeHtml(item.category)}}</span>${{date}}</div>
      <p class="summary">${{escapeHtml(item.summary)}}</p>
      ${{(item.summary_checked && (item.summary_checked.missing || []).length) ? `<div class="check-note">Not found in the source text: ${{escapeHtml(item.summary_checked.missing.join(", "))}}</div>` : ""}}
      ${{(item.action_points && item.action_points.length) ? `<div class="action-points"><strong style="color:#ff9f1c;font-size:13px;">Action Pointers</strong><ul style="margin-top:6px;padding-left:18px;color:#ccc;font-size:13px;line-height:1.8">${{item.action_points.map(a => `<li>${{escapeHtml(a)}}</li>`).join("")}}</ul></div>` : ""}}
      <div class="tags">${{tags}}</div>
    </div>`;
  }}).join("");
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
    var src = (res.sources || []).map(s => `<a href="${{safeHref(s.url)}}" target="_blank" rel="noopener">&#8594; ${{escapeHtml(s.title)}}</a>`).join("");
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
document.querySelectorAll(".filters button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".filters button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.cat;
    render();
  }});
}});
document.getElementById("sort-select").addEventListener("change", e => {{ currentSort = e.target.value; render(); }});
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


RETIRED_TRIAGE_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Content Digest</title></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,sans-serif;padding:40px;max-width:600px;margin:0 auto;">
<h2 style="color:#b17e51;">This link has been retired</h2>
<p>Content Digest no longer asks you to triage saved items one at a time, so this
link changes nothing. Everything you saved is in the knowledge base.</p>
<p style="color:#666;font-size:13px;">You can close this tab.</p>
</body></html>"""


LOCKED_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Content Digest</title></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,sans-serif;padding:40px;max-width:600px;margin:0 auto;">
<h2 style="color:#b17e51;">Locked</h2>
<p>This knowledge base requires a one-time unlock per device.</p>
<p style="color:#888;font-size:14px;">Paste the auth token from secrets.json. A session cookie
keeps this device signed in afterwards; the token itself is not stored.</p>
<!-- GET form to /view?token=... so installed PWAs (own cookie jar, no address
     bar) can unlock themselves without leaving the app. -->
<form method="GET" action="/view" style="display:flex;gap:8px;margin-top:16px;">
  <input type="password" name="token" placeholder="Auth token" autocomplete="off"
         style="flex:1;background:#1e1e1e;border:1px solid #333;color:#e0e0e0;padding:10px 14px;border-radius:10px;font-size:14px;outline:none;">
  <button type="submit"
          style="background:#b17e51;border:none;color:#000;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">Unlock</button>
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

    def _note_contact(self):
        """Call only after auth passed. Bearer callers name themselves with
        X-Client (allowlisted, else 'api'); cookie callers are the /view page."""
        if self._bearer_ok():
            _touch_client(self.headers.get("X-Client", "").strip().lower() or "api")
        else:
            _touch_client("view")

    def _same_origin(self):
        origin = self.headers.get("Origin", "")
        site = self.headers.get("Sec-Fetch-Site", "")
        if site and site not in ("same-origin", "none"):
            return False
        if origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc.lower() != (self.headers.get("Host", "") or "").lower():
                return False
        return True

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
            # Act / Later / Archive links in briefs sent before decision 14.
            # Triage is retired: the link changes nothing and says so, in a
            # plain page rather than an error.
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(RETIRED_TRIAGE_HTML.encode())
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
            _touch_client("view")
            try:
                html = build_html(_load_data()["items"])
                _write_html(html)
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
            self.wfile.write(json.dumps(health_snapshot()).encode())
            return
        if path == "/failures":
            if not self._authed():
                self._deny()
                return
            self._note_contact()
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
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            self._deny(413, "Body too large")
            return
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            body = {}
        authed = self._authed()
        # Route on the path alone: "/state?x=1" or "/state/" must not slip
        # past the retired list into the add path (review, 2026-10).
        route = self.path.split("?", 1)[0].rstrip("/") or "/"

        is_ingest = (route not in ("/delete", "/retry", "/failures/delete", "/ask")
                     and route not in RETIRED_POST_PATHS)

        # Durable inbox capture: record every incoming link before auth and fetch.
        if is_ingest:
            _inbox_url = body.get("url", "").strip()
            if _inbox_url:
                _record_inbox(_inbox_url, authed=authed)

        # Auth gate runs AFTER capture, so a rejected link is still recorded.
        # EVERY POST endpoint requires auth: bearer token (clients) or the
        # session cookie (the /view UI). Mutating endpoints were previously
        # exempt; that exemption was the core of issue #2.
        if not authed:
            self._deny()
            return
        # Cookie-authenticated requests come from the /view page and must be
        # same-origin; a bearer token is a deliberate machine credential and
        # is exempt. Origin/Sec-Fetch-Site are set by every modern browser.
        if not self._bearer_ok() and not self._same_origin():
            self._deny(403, "Cross-origin request refused")
            return
        self._note_contact()

        if route in RETIRED_POST_PATHS:
            self.send_response(410)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "status": "retired"}).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if route == "/delete":
            url = body.get("url", "").strip()
            if url:
                with data_lock:
                    data = _load_data()
                    data["items"] = [i for i in data["items"] if i["url"] != url]
                    _save_data(data)
                _dismiss(url)
                _write_html(build_html(data["items"]))
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if route == "/failures/delete":
            url = body.get("url", "").strip()
            if url:
                _remove_failure(url)
                _dismiss(url)
                _write_html(build_html(_load_data()["items"]))
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if route == "/retry":
            url = body.get("url", "").strip()
            self.wfile.write(json.dumps({"ok": True}).encode())
            if url.startswith(("http://", "https://")):
                threading.Thread(target=process_url, args=(url,), daemon=True).start()
            return

        if route == "/ask":
            question = str(body.get("question", "")).strip()[:500]
            if not question:
                self.wfile.write(json.dumps({"answer": "Ask a question about your saved items.", "sources": []}).encode())
                return
            result = answer_question(question)
            self.wfile.write(json.dumps(result).encode())
            return

        if route == "/add_sync":
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

    def log_request(self, code="-", size="-"):
        """Content-free request log: method, path without query, status, and
        the X-Client header. Never the URL being saved, never a token. Health
        polls and static assets are skipped so the log stays readable."""
        path = self.path.split("?", 1)[0]
        if path == "/health" or path.startswith("/assets/"):
            return
        client = self.headers.get("X-Client", "").strip().lower()
        client = client if client in KNOWN_CLIENTS else ("other" if client else "-")
        print(f"[req] {self.command} {path} {code} client={client}", flush=True)


if __name__ == "__main__":
    BASE_DIR.mkdir(exist_ok=True)
    try:
        # One-time data migrations (backup first, marker in the data folder).
        # Imported here, not at the top: the host's deploy check compiles
        # server.py but not migrations.py, so even a broken module must only
        # log a line. A failure never stops capture from starting.
        import migrations
        migrations.run(BASE_DIR, now=datetime.now(TZ), log=lambda m: print(m, flush=True))
    except Exception as e:
        print(f"[migrate] skipped: {type(e).__name__}: {e}", flush=True)
    _self_heal_failures()
    threading.Thread(target=retry_loop, daemon=True).start()
    threading.Thread(target=backfill_embeddings, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7778
    # ThreadingHTTPServer: a slow /ask or /add_sync must never block the
    # iPhone shortcut, the menu bar client, or the Chrome extension.
    addresses = _bind_addresses_from_config()
    servers = _bind_servers(addresses, port, Handler) if addresses else []
    if not servers:
        if addresses:
            print(f"[server] WARNING: none of {addresses} could be bound; falling back to 0.0.0.0 "
                  "so capture stays up (the source allowlist still applies)", flush=True)
        servers = [ThreadingHTTPServer(("0.0.0.0", port), Handler)]
    bound = ", ".join(f"{s.server_address[0]}:{s.server_address[1]}" for s in servers)
    print(f"[server] Content Digest server v{SERVER_VERSION} starting on {bound}", flush=True)
    for extra in servers[1:]:
        threading.Thread(target=extra.serve_forever, daemon=True).start()
    servers[0].serve_forever()
