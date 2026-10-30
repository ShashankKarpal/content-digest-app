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
import http.client
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "macos:content-digest:v0.4 (personal knowledge tool)"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")
MAX_CONTENT = 3000
ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"

# Short-link hosts that must be resolved to their destination BEFORE dedupe,
# storage, and extraction. lnkd.in is the big one: LinkedIn serves the target
# post at HTTP 200 after redirects, but the visible DOM is an authwall, so the
# short link must never be the stored identity.
_SHORTENER_HOSTS = {
    "lnkd.in", "bit.ly", "t.co", "tinyurl.com", "buff.ly", "ow.ly",
    "goo.gl", "rebrand.ly", "cutt.ly", "t.ly", "shorturl.at", "rb.gy",
}
MAX_SHORT_LINK_HOPS = 5
SHORT_LINK_TIMEOUT = 10


# ---------------------------------------------------------------------------
# SSRF guard. Moved here from server.py (2026-10) unchanged, so that the
# short-link resolver below checks every redirect hop with the same guard the
# server applies to the URL it is asked to save. server.py imports it as
# _blocked_url_reason.
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = {"example.com", "example.org", "example.net", "localhost", "test.com"}

_PRIVATE_IP_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|0\.0\.0\.0|169\.254\."
    r"|172\.(1[6-9]|2\d|3[01])\."          # 172.16/12
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)"  # 100.64/10 CGNAT incl. Tailscale
)


def _address_is_internal(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        # ::ffff:100.100.1.1 is the tailnet address 100.100.1.1; the IPv6
        # checks below do not know the 100.64/10 range (security review,
        # 2026-10-30).
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified
            or ip in ipaddress.ip_network("100.64.0.0/10"))   # CGNAT incl. Tailscale


def blocked_url_reason(url, resolve=True):
    """Reject URLs that can never be real content, and URLs the server must
    never fetch: non-http schemes, and hosts that resolve to loopback, RFC1918,
    link-local, or the tailnet range. The literal-IP regex alone let a public
    hostname pointing at 127.0.0.1 (or an IPv6 literal, or file://) through
    to urlopen (audit 2026-09-02). Call again on the post-redirect URL."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        scheme = (parts.scheme or "").lower()
    except Exception:
        return "Unparseable URL"
    if scheme not in ("http", "https"):
        return f"Unsupported scheme: {scheme or 'none'}"
    if not host:
        return "URL has no host"
    host = host.lower()
    bare = host[4:] if host.startswith("www.") else host
    if bare in _BLOCKED_HOSTS:
        return f"Placeholder/test domain: {bare}"
    if _PRIVATE_IP_RE.match(bare) or bare.endswith(".local") or bare.endswith(".localhost") \
            or bare == "localhost" or _address_is_internal(bare):
        return f"Local/private address: {bare}"
    if resolve:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return None   # unresolvable: let the fetch fail with its own reason
        except Exception:
            return None
        for info in infos:
            addr = info[4][0]
            if _address_is_internal(addr):
                return f"Host resolves to an internal address: {bare} -> {addr}"
    return None


def _bare_host(url):
    """Lowercase host without www. and without a port."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_short_link(url):
    """True when url is on a known shortener host."""
    return _bare_host(url) in _SHORTENER_HOSTS


# DNS rebinding (leak audit M4, 2026-10): blocked_url_reason asks DNS where a
# name points, and the connection used to ask again. A name that answers a
# public address the first time and an inside one the second slipped past.
# Every fetch now resolves once at connect time, checks each address, and
# connects to a checked address. TLS still verifies the certificate against
# the host name. Proxies are off for these openers: a proxy would resolve the
# name itself, out of the guard's sight.

def _dial(family, socktype, proto, sockaddr, timeout, source_address):
    """Connect one socket to one already-checked address."""
    sock = socket.socket(family, socktype, proto)
    try:
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        if source_address:
            sock.bind(source_address)
        sock.connect(sockaddr)
        return sock
    except BaseException:
        sock.close()
        raise


def _checked_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    """socket.create_connection that refuses a name with any inside address."""
    host, port = address[0], address[1]
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for info in infos:
        if _address_is_internal(info[4][0]):
            raise OSError(f"refused: {host} resolves to an internal address at connect time")
    error = None
    for family, socktype, proto, _, sockaddr in infos:
        try:
            return _dial(family, socktype, proto, sockaddr, timeout, source_address)
        except OSError as e:
            error = e
    raise error or OSError(f"no address for {host}")


class _CheckedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _checked_connection


class _CheckedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _checked_connection


class _CheckedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_CheckedHTTPConnection, req)


class _CheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_CheckedHTTPSConnection, req, context=self._context)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only after its target passes blocked_url_reason."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        reason = blocked_url_reason(newurl)
        if reason:
            raise urllib.error.URLError(f"redirect refused: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_GUARDED_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _CheckedHTTPHandler, _CheckedHTTPSHandler, _GuardedRedirect)


def guarded_urlopen(req, timeout):
    """urlopen that runs the SSRF guard on the first URL and on every redirect
    target before requesting it. Plain urlopen followed up to 10 redirects
    unchecked, so a public URL could bounce the server into its own network,
    and some callers (normalize_url resolving a reddit share link) fetch
    before process_url's own check runs (review, 2026-10)."""
    reason = blocked_url_reason(req.full_url)
    if reason:
        raise urllib.error.URLError(f"refused: {reason}")
    return _GUARDED_OPENER.open(req, timeout=timeout)


def _get(url, timeout=20, headers=None):
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with guarded_urlopen(req, timeout=timeout) as r:
        # 2 MB cap: the runtime host has 8 GB and an unbounded read is a
        # memory DoS from any page we are asked to fetch (audit 2026-09-02).
        return r.read(2_000_000).decode("utf-8", errors="ignore"), r.geturl()


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand every 3xx back to the caller instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _CheckedHTTPHandler, _CheckedHTTPSHandler, _NoRedirect)
_LNKD_EXTERNAL_LINK_RE = re.compile(r'<a\b[^>]*data-tracking-control-name="external_url_click"[^>]*>', re.I)


def _fetch_hop(url, timeout=SHORT_LINK_TIMEOUT):
    """One request with redirects off. Returns (status, location, body)."""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as r:
            return r.status, None, r.read(200_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return e.code, e.headers.get("Location"), ""
        raise


def _lnkd_interstitial_target(body):
    """A bare lnkd.in/<code> link answers 200 with a "leaving LinkedIn" page,
    not a redirect (verified 2026-10-22); the destination is the href of the
    page's external_url_click link."""
    m = _LNKD_EXTERNAL_LINK_RE.search(body or "")
    href = re.search(r'href="([^"]+)"', m.group(0)) if m else None
    return html_mod.unescape(href.group(1)) if href else None


def _resolve_short_link(url):
    """Follow a known shortener to its destination one hop at a time. Each hop,
    the destination included, passes blocked_url_reason (scheme, private and
    tailnet addresses, DNS answers) BEFORE it is requested, so a short link
    can never walk the server into its own network (red team, 2026-10). The
    walk stops at the first URL that is not on a shortener host; that URL is
    returned, never fetched. None when a hop is blocked, unreadable, or the
    chain is longer than MAX_SHORT_LINK_HOPS. Only a result is cached: a
    failure may be a network blip, and caching it would fail every retry
    until the server restarts (review, 2026-10)."""
    if url in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[url]
    current, final, hops = url, None, 0
    while True:
        if blocked_url_reason(current):
            break
        host = _bare_host(current)
        if host not in _SHORTENER_HOSTS:
            final = current
            break
        if hops >= MAX_SHORT_LINK_HOPS:
            break
        hops += 1
        try:
            _, location, body = _fetch_hop(current)
        except Exception:
            break
        nxt = urllib.parse.urljoin(current, location) if location else (
            _lnkd_interstitial_target(body) if host == "lnkd.in" else None)
        if not nxt:
            break
        current = nxt
    if final:
        _RESOLVE_CACHE[url] = final
    return final


def strip_tracking(url):
    """Layer 1 of normalize_url: drop tracking parameters and the fragment,
    lowercase scheme and host. No network."""
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
    return urllib.parse.urlunsplit((p.scheme.lower(), host, p.path, query, ""))


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

        # Short links: resolve to the destination and normalize THAT instead,
        # so a lnkd.in link and its linkedin.com target dedupe to one item.
        if bare_host in _SHORTENER_HOSTS:
            resolved = _resolve_short_link(url.strip())
            if resolved and resolved != url.strip():
                return normalize_url(resolved)

        cleaned = strip_tracking(url)

        # Layer 2: per-site canonical identity. Exact hosts only: a loose
        # endswith("reddit.com") sent lookalikes such as xreddit.com to the
        # share-link fetch (review, 2026-10).
        if bare_host == "reddit.com" or bare_host.endswith(".reddit.com") or bare_host == "redd.it":
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
# LinkedIn: public post pages carry the full post in JSON-LD + og meta tags.
# The visible DOM is an authwall ("Agree & Join LinkedIn"), which is why the
# generic trafilatura path must NEVER be used for linkedin.com / lnkd.in.
# ---------------------------------------------------------------------------

_AUTHWALL_MARKERS = (
    "agree & join linkedin", "authwall", "join now to see",
    "manage your professional identity", "sign up | linkedin",
    "500 million+ members",
)


def fetch_linkedin_content(url):
    if urllib.parse.urlsplit(url).netloc.lower().endswith("lnkd.in"):
        resolved = _resolve_short_link(url)
        if not resolved:
            print(f"[linkedin] short link did not resolve: {url[:60]}")
            return None
        url = resolved
    try:
        page, final = _get(url, timeout=20, headers={"User-Agent": BROWSER_UA})
    except Exception as e:
        print(f"[linkedin] fetch failed ({type(e).__name__}: {e})")
        return None
    # Landed on the signup/authwall page instead of the post: fail cleanly.
    if any(k in (final or "") for k in ("/signup", "/authwall", "session_redirect")):
        print(f"[linkedin] redirected to authwall: {final[:60]}")
        return None

    title, body, author, comments = "", "", "", []

    # Primary: JSON-LD SocialMediaPosting / Article
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") in ("SocialMediaPosting", "Article", "NewsArticle", "BlogPosting"):
                title = node.get("headline") or title
                body = node.get("articleBody") or node.get("text") or body
                a = node.get("author")
                if isinstance(a, dict):
                    author = a.get("name") or author
                for c in (node.get("comment") or [])[:5]:
                    if isinstance(c, dict) and c.get("text"):
                        comments.append(c["text"][:300])

    # Fallback: og meta tags (og:description holds the post text on public posts)
    if not body:
        m = re.search(r'property="og:description"\s+content="([^"]*)"', page)
        if m:
            body = html_mod.unescape(m.group(1))
        m = re.search(r'property="og:title"\s+content="([^"]*)"', page)
        if m and not title:
            title = html_mod.unescape(m.group(1))

    body = (body or "").strip()
    low = body.lower()
    # No real content, or content IS the authwall: fail cleanly. The failure
    # guard notifies, and the Chrome extension (logged in) is the escape hatch.
    if len(body) < 80 or any(k in low for k in _AUTHWALL_MARKERS):
        print(f"[linkedin] no public content (authwall?): {final[:60]}")
        return None

    parts = [f"LinkedIn post{' by ' + author if author else ''}: {html_mod.unescape(title)}", "", html_mod.unescape(body)]
    if comments:
        parts += ["", "Top comments:"] + [html_mod.unescape(c) for c in comments]
    text = "\n".join(parts)
    print(f"[linkedin] extracted ok: {final[:60]}")
    return text[:MAX_CONTENT]


# ---------------------------------------------------------------------------
# Links inside a saved post (decision 14, 2026-10): what the post points to
# ---------------------------------------------------------------------------

_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_BARE_SHORT_LINK_RE = re.compile(
    r"(?<![\w./@-])((?:" + "|".join(re.escape(h) for h in sorted(_SHORTENER_HOSTS)) + r")/[A-Za-z0-9_-]+)",
    re.I)
_TRAILING_PUNCTUATION = ".,;:!?)]}>'\"*"


def find_links(text):
    """http(s) URLs in plain text, plus bare short links such as lnkd.in/abc
    (LinkedIn shows them without a scheme), in the order they appear.
    Trailing punctuation is dropped and repeats go."""
    hits = [(m.start(), m.group(0).rstrip(_TRAILING_PUNCTUATION)) for m in _URL_IN_TEXT_RE.finditer(text or "")]
    hits += [(m.start(), "https://" + m.group(1)) for m in _BARE_SHORT_LINK_RE.finditer(text or "")]
    found = []
    for _, link in sorted(hits):
        if link not in found:
            found.append(link)
    return found


def artifact_urls(text, own_url="", limit=10, max_short_links=5):
    """What a saved post links to: the links in its extracted text, which for
    LinkedIn and Reddit includes the top comments the extractors already
    fetch. Short links are resolved hop by hop (_resolve_short_link), at most
    max_short_links of them, and an unresolved one is left out. Every kept URL
    passed blocked_url_reason; the item's own URL is skipped. Network: one
    DNS lookup per link for the guard, plus the short link hops; no page is
    fetched."""
    own = strip_tracking(own_url) if own_url else ""
    out, short_links = [], 0
    for link in find_links(text):
        if len(out) >= limit:
            break
        if _bare_host(link) in _SHORTENER_HOSTS:
            if short_links >= max_short_links:
                continue
            short_links += 1
            target = _resolve_short_link(link)
            if not target:
                continue
        elif blocked_url_reason(link):
            continue
        else:
            target = link
        clean = strip_tracking(target)
        if clean and clean != own and clean not in out:
            out.append(clean)
    return out


def container_page_reason(url):
    """A feed or home page is never an item: saving it would make every later
    save of the same page look like a duplicate (2026-09-03 decision). Mirrors
    isContainerUrl in extension/shared.js; the server applies it to every
    capture path, not only the extension. Returns the reason, or None."""
    host = _bare_host(url)
    try:
        path = urllib.parse.urlsplit(url).path.rstrip("/") or "/"
    except Exception:
        return None
    if ((host == "linkedin.com" or host.endswith(".linkedin.com")) and path in ("/", "/feed", "/mynetwork")) \
            or ((host == "reddit.com" or host.endswith(".reddit.com")) and path in ("/", "/r/all", "/r/popular")) \
            or (host == "news.ycombinator.com" and path in ("/", "/news", "/newest")):
        return "A feed page, not a post: save the post's own link (on LinkedIn, the post menu's Copy link to post)"
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
    # Exclusive: the generic path on LinkedIn extracts the authwall and turns
    # it into a junk item ("Agree & Join LinkedIn"). Fail clean instead.
    if bare == "linkedin.com" or bare.endswith(".linkedin.com") or bare == "lnkd.in":
        return fetch_linkedin_content, True
    return None, False
