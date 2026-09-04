# docs/architecture.md

## System Architecture — Content Digest App (v0.4)

### Extension capture rewrite (v0.6 candidate, 2026-09-03)

The server shape is unchanged. Every extension capture now uses authenticated
`POST /add_sync`, so the client receives `saved`, `already_saved`, `failed`, or
`invalid` after processing instead of treating an early HTTP 200 as success.

The MV3 extension remains plain JavaScript with no build step, bundler, or
dependency. Files and responsibilities:

- `popup.html` and `popup.js` implement the primary paste-first workflow. The
  toolbar icon opens a popup with an empty URL field; the user pastes the exact
  URL and clicks Send to Content Digest. The popup shows a working state, then
  the honest outcome (saved, already saved, queued, refused, failed), plus
  Save current page, Open Content Digest, Settings, a collapsed recent-activity
  list, and the retry queue count. The field is never prefilled from the tab.
- `shared.js` owns URL unwrapping for known redirector wrappers (LinkedIn
  safety/go, Google, Facebook, Reddit, href.li, away.vk.com), container
  detection, LinkedIn post detection, and identity selection.
- `content.js` handles page-specific capture for the optional right-click path.
  It records the exact right-click target and uses ordinary DOM extraction when
  a post permalink or `urn:li:activity` URN is genuinely present in the markup.
- `bridge.js` runs narrowly on `https://*.linkedin.com/*` in the MAIN world. It
  wraps `navigator.clipboard.writeText` and re-emits the written text as a DOM
  event. `content.js` listens for that event only while an explicit post
  resolution is pending: after the user has asked to save, it opens LinkedIn's
  own post menu, invokes LinkedIn's own Copy link to post action, and accepts
  only a post-shaped LinkedIn URL or `lnkd.in/p/` short link from the result.
  The bridge never logs, stores, or transmits clipboard text, and the listener
  is removed when resolution finishes or times out (2 seconds).
- `background.js` owns submission through authenticated `POST /add_sync`,
  badges, the capped 100-item retry queue with its 15-minute alarm, and a
  persistent five-result history. Before POSTing it resolves a post-shaped
  `lnkd.in/p/<code>` short link by following the redirect and submits the final
  direct `linkedin.com` post URL.

LinkedIn feed and container URLs are never valid item identities. A feed
toolbar or page action is refused with a visible instruction to paste a
permalink. A `linkedin.com/safety/go/?url=` wrapper is decoded first; if it
decodes to a bare, non-redirecting `lnkd.in/<code>`, the containing post
permalink is used when one can be determined, otherwise the capture is refused
instead of poisoning dedupe. A bare non-post short link is never treated as a
saved content item.

Settings still live only in `chrome.storage.local`. A fresh install stores no
server default. The guarded `migratedFromSync` migration, unconditional sync
purge, 15-minute alarm, 100-item queue cap, bearer header, and 20,000-character
browser-content cap remain in place.

### v0.4 additions (2026-07-19)

**extractors.py** (new): source-aware extraction registry, imported by server.py.
- Reddit: old.reddit.com HTML primary (post + top comments, sort=top), arctic-shift archive API fallback. Exclusive routing: on failure the generic path is skipped (direct fetch 403s, jina IPs banned by Reddit).
- YouTube: oEmbed title + youtube-transcript-api transcript. No transcript, no summary (failure guard, not hallucination).
- X/Twitter: api.fxtwitter.com mirror.
- normalize_url(): strips utm_*, fbclid, share_id, si and friends before dedup and storage.

**server.py additions:**
- fetch_url_content dispatches to extractors first; generic trafilatura + jina path unchanged for everything else.
- process_url(url, content=None): optional pre-fetched content (Chrome extension) skips fetching entirely.
- validate_analysis(): category whitelist, relevance clamped 1-5, shape checks before save.
- Item states: "state" field ("", act, revisit, archive), POST /state, filtered in UI, archived excluded from daily brief.
- POST /ask: Ollama embeddings (nomic-embed-text at localhost:11434, embeddings.json cache, backfill at startup) with keyword fallback; answers via qwen/Groq with cited sources.
- retry_loop(): every 6h retries fetch failures (max 3) and re-queues orphaned inbox URLs.
- Groq fallback: model llama-3.1-8b-instant, custom User-Agent (default Python UA is 403'd by Groq edge).

**extension/** (new): Manifest V3 Chrome extension. Sends {url, title, content} of the rendered page to /add with the Bearer token. The unblockable capture path for Reddit, LinkedIn, and future walled sites. Replaces the retired reddit-tab-harvester fork.

**Data files:** knowledge.json (+state field), embeddings.json (url -> vector), inbox.json, failures.json.

---

## Original v0.1 architecture (historical, superseded where noted above)

---

## Components

### 1. Menu Bar App
- File: ~/content-digest-app/app.py
- Framework: Python rumps (Mac menu bar), AppKit NSApp for dialogs.
- Icon: 📌
- Entry point: user clicks icon or iPhone sends a URL. App shows osascript dialog for manual URL input (appears above all windows including Chrome).
- Auto-starts on boot via LaunchAgent.

### 2. LaunchAgent
- File: ~/Library/LaunchAgents/com.shashank.contentdigest.plist
- Starts app.py automatically on Mac boot.
- Desktop shortcut at ~/Desktop/Content Digest.command for manual start.

### 3. iPhone Receiver
- Endpoint: POST to http://<mac-lan-ip>:7778/add
- Accepts JSON payload with URL from iOS Shortcuts.
- iOS Shortcut named "Save to Content Digest" appears in share sheet of any app.
- Mac IP: <mac-lan-ip> (may change, update shortcut if it stops working).
- Known issue: receiver currently binds to 0.0.0.0. Should bind to localhost or use auth token.

### 4. Content Extraction
- Current: regex-based HTML stripping. Known to produce noisy, garbage-heavy output.
- Target: trafilatura. Proper reader, understands document structure, ignores navigation and ads automatically.
- This change is must-have for v0.1 before testing summaries.

### 5. LM Studio (Local LLM)
- Model: qwen2.5-14b-instruct-1m
- Server: localhost:1234
- API format: OpenAI-compatible, endpoint /v1/chat/completions
- Context: 32305 tokens
- Produces: 150-200 word summary, auto-category (Work, Learning, Entertainment, News, Ideas), auto-tags, action pointers.

### 6. Storage
- File: ~/content-digest-app/knowledge.json
- Format: JSON array of saved items.
- Known issue: delete action only removes UI element, does not write deletion back to knowledge.json. Items persist invisibly.

### 7. Knowledge Base UI
- File: ~/content-digest-app/knowledge.html
- Dark UI, Montserrat font.
- Opened via "Show" button in Mac notifications.
- Known issue: HTML output not sanitized against LLM-generated or URL-influenced content.

### 8. Chrome Extension (Separate Repo)
- Location: ~/content-digest/
- GitHub: https://github.com/ShashankKarpal/content-digest
- Server runs on port 7777.
- Forked from sunlesshalo/reddit-tab-harvester.
- Modified to use LM Studio instead of Anthropic API.
- Currently blocked by Reddit 403 errors. Reddit API approval pending for app named "content-digest".
- Not a dependency for v0.1.

---

## Data Flow

```
iPhone (Shortcuts) ----POST /add:7778----> app.py
Mac dialog (osascript) ----------------> app.py
                                            |
                                     Fetch URL content
                                     (currently regex, target: trafilatura)
                                            |
                                     LM Studio /v1/chat/completions
                                            |
                                     knowledge.json (append)
                                            |
                                     knowledge.html (regenerate)
                                            |
                                     Mac notification (with Show button)
```

---

## Known Weak Points

1. Regex content extraction: produces noisy LLM input, likely degrades summary quality.
2. Delete not persistent: items remain in knowledge.json after UI deletion.
3. Receiver exposed on 0.0.0.0: unnecessary security surface.
4. LLM output not validated: no check on JSON shape, category values, or relevance bounds before saving.
5. Hardcoded values: model name, port, endpoint, file paths are hardcoded in app.py. Should move to config.
6. HTML not sanitized: LLM output and URL-influenced fields written directly to HTML.
7. No deduplication: same URL with different tracking params may be saved multiple times.
8. No concurrency protection: concurrent saves could overwrite knowledge.json.

---

## Constraints

- Fully local: no cloud APIs, no third-party services.
- LM Studio must be running for summarization to work.
- Mac IP (<mac-lan-ip>) may change. iPhone shortcut must be updated manually if it does.
- Python at /opt/homebrew/bin/python3 (version 3.14).
- User edits files via Terminal heredoc or python3 -c, not TextEdit (causes indentation issues).
