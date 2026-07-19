#!/usr/bin/env python3
"""Source-aware content extractors for Content Digest.

Registry of site-specific fetchers. Each extractor takes a URL and returns
plain text ready for summarization (capped at 3000 chars), or None on failure.
Generic sites keep using trafilatura in server.py; this module handles sites
that block direct fetching or need structure-aware extraction.

Verified 2026-07-19:
- Reddit .json endpoints are dead (403 since Dec 2025). old.reddit.com HTML
  returns 200 from residential IPs (~100 req/10 min). Primary path.
- arctic-shift.photon-reddit.com archive API works, ~0.4h freshness lag. Fallback.
- api.fxtwitter.com works for X/Twitter posts.
- YouTube oEmbed works without a key; transcripts via youtube-transcript-api.
"""

import html as html_mod
import json
import re
import urllib.parse
import urllib.request

USER_AGENT = "macos:content-digest:v0.4 (personal knowledge tool)"
MAX_CONTENT = 3000
ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"


def _get(url, timeout=20, headers=None):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore"), r.geturl()


# ---------------------------------------------------------------------------
# URL normalization (strip tracking params so dedup works)
# ---------------------------------------------------------------------------

_GLOBAL_TRACKING = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "igsh", "spm", "share_id", "cmpid", "mkt_tok",
}
_DOMAIN_TRACKING = {
    "x.com": {"s", "t"},
    "twitter.com": {"s", "t"},
    "youtube.com": {"si", "feature", "pp"},
    "youtu.be": {"si", "feature"},
    "reddit.com": {"share_id", "ref", "ref_source", "context", "st", "sh", "rdt", "utm_name"},
    "linkedin.com": {"rcm", "trk", "originalSubdomain", "midToken", "midSig", "trkEmail"},
}

# Cache for resolved share/short links so inbox sweeps do not re-resolve.
_RESOLVE_CACHE = {}


def normalize_url(url):
    """Canonical URL identity for dedup and storage.

    Layer 1 (all sites): strip tracking params and fragments, lowercase host.
    Layer 2 (known sites): collapse every alias of the same content to ONE
    canonical form, so e.g. a reddit /s/ share link, redd.it short link,
    old.reddit URL, and the full www.reddit.com URL are all the same item.
    """
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = p.netloc.lower()
        bare_host = host[4:] if host.startswith("www.") else host
        domain_strip = set()
        for dom, params in _DOMAIN_TRACKING.items():
            if bare_host == dom or bare_host.endswith("." + dom):
                domain_strip = params
                break
        kept = []
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True):
            if k.lower().startswith("utm_"):
                continue
            if k.lower() in _GLOBAL_TRACKING or k in domain_strip:
                continue
            kept.append((k, v))
        query = urllib.parse.urlencode(kept)
        cleaned = urllib.parse.urlunsplit((p.scheme.lower(), host, p.path, query, ""))

        # Layer 2: per-site canonical identity
        if bare_host.endswith("reddit.com") or bare_host == "redd.it":
            canonical = _canonical_reddit(cleaned)
            if canonical:
                return canonical
        elif bare_host in ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"):
            vid = _youtube_id(cleaned)
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        elif bare_host in ("twitter.com", "mobile.twitter.com"):
            return cleaned.replace("//" + host, "//x.com", 1).replace("//www.twitter.com", "//x.com", 1)
        return cleaned
    except Exception:
        return url


def _canonical_reddit(url):
    """One canonical URL per reddit thread. Resolves /s/ share links and
    redd.it short links (cached), then rebuilds a slug-free thread URL so
    every alias of the same thread collapses to the same identity."""
    tid = _reddit_thread_id(url)
    if not tid:
        if url in _RESOLVE_CACHE:
            url = _RESOLVE_CACHE[url]
        else:
            resolved = _resolve_reddit_url(url)
            _RESOLVE_CACHE[url] = resolved
            url = resolved
        tid = _reddit_thread_id(url)
        if not tid:
            return None
    sub = re.search(r"/r/([^/]+)/", url)
    if sub:
        return f"https://www.reddit.com/r/{sub.group(1)}/comments/{tid}/"
    return f"https://www.reddit.com/comments/{tid}/"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _strip_html(fragment):
    """Convert an HTML fragment to readable plain text."""
    t = re.sub(r"<li[^>]*>", "\n- ", fragment)
    t = re.sub(r"</?(p|br|blockquote|pre|h[1-6]|tr)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html_mod.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Reddit: old.reddit.com HTML primary, arctic-shift archive fallback
# ---------------------------------------------------------------------------

_REDDIT_HOSTS = ("reddit.com", "old.reddit.com", "www.reddit.com", "redd.it", "new.reddit.com", "np.reddit.com")


def _reddit_thread_id(url):
    m = re.search(r"/comments/([a-z0-9]+)", url)
    return m.group(1) if m else None


def _resolve_reddit_url(url):
    """Resolve redd.it and /s/ share links to a canonical thread URL."""
    if _reddit_thread_id(url):
        return url
    try:
        _, final = _get(url, timeout=15)
        return final
    except Exception:
        return url


def _reddit_via_old(url):
    tid_url = re.sub(r"^https?://(www\.|new\.|np\.)?reddit\.com", "https://old.reddit.com", url)
    if "old.reddit.com" not in tid_url:
        return None
    sep = "&" if "?" in tid_url else "?"
    page, _ = _get(f"{tid_url}{sep}sort=top&limit=500", timeout=25)

    tm = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html_mod.unescape(tm.group(1)).rsplit(" : ", 1)[0].strip() if tm else url
    sub = re.search(r"/r/([^/]+)/", url)
    subreddit = sub.group(1) if sub else ""

    ca = page.find('class="commentarea"')
    if ca == -1:
        ca = len(page)
    head, tail = page[:ca], page[ca:]

    # Selftext: md blocks between the post table and the comment area
    st_pos = head.find('id="siteTable"')
    post_zone = head[st_pos:] if st_pos != -1 else ""
    selftext_blocks = re.findall(r'<div class="md">(.*?)</div>', post_zone, re.S)
    selftext = "\n".join(_strip_html(b) for b in selftext_blocks).strip()
    if not selftext:
        lm = re.search(r'data-url="([^"]+)"', post_zone)
        selftext = f"(link post: {html_mod.unescape(lm.group(1))})" if lm else "(no post body)"

    # Comments: pair each md block with the nearest preceding score
    comments = []
    last_score = "?"
    for m in re.finditer(
        r'<span class="score unvoted" title="(-?\d+)">|<div class="md">(.*?)</div>',
        tail, re.S,
    ):
        if m.group(1) is not None:
            last_score = m.group(1)
        else:
            body = _strip_html(m.group(2))
            if body and len(body) > 2:
                comments.append((last_score, body[:400]))
                last_score = "?"
        if len(comments) >= 12:
            break

    parts = [f"Reddit thread in r/{subreddit}: {title}", "", "Post:", selftext[:1200]]
    if comments:
        parts += ["", "Top comments:"]
        parts += [f"[{s} points] {c}" for s, c in comments]
    text = "\n".join(parts)
    return text[:MAX_CONTENT] if len(text) > 200 else None


def _reddit_via_arctic(url):
    tid = _reddit_thread_id(url)
    if not tid:
        return None
    body, _ = _get(f"{ARCTIC_BASE}/posts/ids?ids={tid}", timeout=25)
    posts = json.loads(body).get("data", [])
    if not posts:
        return None
    post = posts[0]
    title = post.get("title", url)
    subreddit = post.get("subreddit", "")
    selftext = re.sub(r"\\([\[\]()_*~`#])", r"\1", (post.get("selftext") or "").strip())
    if not selftext:
        ext = post.get("url", "")
        selftext = f"(link post: {ext})" if ext and tid not in ext else "(no post body)"

    comments = []
    try:
        cbody, _ = _get(f"{ARCTIC_BASE}/comments/tree?link_id={tid}&limit=50", timeout=25)
        raw = json.loads(cbody).get("data", [])
        flat = []

        def walk(nodes, depth=0):
            for n in nodes:
                d = n.get("data", n)
                if d.get("body"):
                    flat.append(d)
                kids = n.get("children") or d.get("children") or []
                if isinstance(kids, list) and depth < 2:
                    walk(kids, depth + 1)

        walk(raw)
        flat.sort(key=lambda c: c.get("score", 0) or 0, reverse=True)
        for c in flat[:12]:
            body_text = re.sub(r"\\([\[\]()_*~`#])", r"\1", c["body"].strip())
            comments.append((c.get("score", "?"), body_text[:400]))
    except Exception:
        pass

    parts = [f"Reddit thread in r/{subreddit}: {title}", "", "Post:", selftext[:1200]]
    if comments:
        parts += ["", "Top comments:"]
        parts += [f"[{s} points] {c}" for s, c in comments]
    return "\n".join(parts)[:MAX_CONTENT]


def fetch_reddit_content(url):
    """Primary: old.reddit HTML. Fallback: arctic-shift archive. None if both fail."""
    url = _resolve_reddit_url(url)
    try:
        text = _reddit_via_old(url)
        if text:
            print(f"[reddit] old.reddit ok: {url[:60]}")
            return text
    except Exception as e:
        print(f"[reddit] old.reddit failed ({type(e).__name__}: {e}), trying arctic-shift")
    try:
        text = _reddit_via_arctic(url)
        if text:
            print(f"[reddit] arctic-shift ok: {url[:60]}")
            return text
    except Exception as e:
        print(f"[reddit] arctic-shift failed ({type(e).__name__}: {e})")
    return None


# ---------------------------------------------------------------------------
# YouTube: oEmbed title + transcript
# ---------------------------------------------------------------------------

def _youtube_id(url):
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def fetch_youtube_content(url):
    vid = _youtube_id(url)
    if not vid:
        return None
    title, author = "", ""
    try:
        body, _ = _get(
            "https://www.youtube.com/oembed?url="
            + urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}")
            + "&format=json", timeout=15)
        j = json.loads(body)
        title, author = j.get("title", ""), j.get("author_name", "")
    except Exception:
        pass
    transcript = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:  # v1.x API
            fetched = YouTubeTranscriptApi().fetch(vid)
            transcript = " ".join(s.text for s in fetched)
        except (AttributeError, TypeError):  # legacy API
            fetched = YouTubeTranscriptApi.get_transcript(vid)
            transcript = " ".join(s["text"] for s in fetched)
    except Exception as e:
        print(f"[youtube] transcript unavailable ({type(e).__name__})")
    if not transcript:
        return None  # fall back to the fetch failure guard rather than hallucinate
    text = f"YouTube video: {title}\nChannel: {author}\n\nTranscript:\n{transcript}"
    return text[:MAX_CONTENT]


# ---------------------------------------------------------------------------
# X / Twitter: fxtwitter mirror API
# ---------------------------------------------------------------------------

def fetch_x_content(url):
    m = re.search(r"/status/(\d+)", url)
    if not m:
        return None
    try:
        body, _ = _get(f"https://api.fxtwitter.com/status/{m.group(1)}", timeout=15)
        j = json.loads(body)
        tw = j.get("tweet") or {}
        if not tw.get("text"):
            return None
        author = tw.get("author") or {}
        parts = [
            f"Post on X by {author.get('name', '')} (@{author.get('screen_name', '')}):",
            "",
            tw["text"],
        ]
        q = tw.get("quote")
        if q and q.get("text"):
            qa = q.get("author") or {}
            parts += ["", f"Quoting @{qa.get('screen_name', '')}:", q["text"]]
        stats = f"\n({tw.get('likes', 0)} likes, {tw.get('retweets', 0)} reposts)"
        text = "\n".join(parts) + stats
        print(f"[x] fxtwitter ok: {url[:60]}")
        return text[:MAX_CONTENT]
    except Exception as e:
        print(f"[x] fxtwitter failed ({type(e).__name__}: {e})")
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get_extractor(url):
    """Return (extractor_fn, exclusive) for the URL, or (None, False).

    exclusive=True means: if the extractor fails, do NOT try the generic
    path (it is known-blocked for that site and only wastes timeouts).
    """
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return None, False
    bare = host[4:] if host.startswith("www.") else host
    if any(bare == h or bare.endswith("." + h.split("/")[0]) for h in ("reddit.com", "redd.it")) or bare in _REDDIT_HOSTS:
        return fetch_reddit_content, True
    if bare in ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"):
        return fetch_youtube_content, False
    if bare in ("x.com", "twitter.com", "mobile.twitter.com"):
        return fetch_x_content, False
    return None, False
