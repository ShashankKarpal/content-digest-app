# Content Digest

A local Mac menu bar app that saves URLs, summarizes them with a local LLM, and builds a personal knowledge base. No cloud. No subscriptions. Runs entirely on your machine.

---

## What It Does

- Click the 📌 icon in your Mac menu bar, paste any URL, get a 150-200 word AI summary with action pointers in seconds.
- Share any URL from your iPhone via the iOS Shortcuts share sheet and it lands in the same knowledge base.
- Auto-categorizes into Work, Learning, Entertainment, News, or Ideas.
- Auto-tags every item.
- Stores everything locally in knowledge.json.
- Displays in a dark, searchable knowledge base UI with filters and sort.

---

## Current Version: v0.4

**Goal:** Reddit works, people return (item states), and the knowledge base answers questions.

### What Is New in v0.4 (July 2026)

- **Reddit summaries work.** No API approval needed: threads are fetched from old.reddit.com (post + top comments), with the arctic-shift archive as automatic fallback. Reddit's official Data API closed to new apps in Nov 2025; this route is verified working.
- **Source-aware extractors** (extractors.py): Reddit threads, YouTube transcripts, X posts via fxtwitter. Everything else keeps using trafilatura.
- **Item states:** mark any card Act / Later / Archive. States show in the UI, filter the knowledge base, and appear as pills in the morning brief. Archived items are excluded from the brief.
- **Ask your knowledge base:** a question box above the filters. Uses local Ollama embeddings (nomic-embed-text) with keyword fallback, answers with cited sources.
- **Self-healing capture:** fetch failures auto-retry every 6 hours (max 3 attempts); inbox URLs that never became items are re-queued.
- **URL normalization:** tracking params (utm_*, fbclid, share_id, si...) stripped before dedup and storage.
- **LLM output validation:** category whitelist, relevance bounds, shape checks before anything is saved.
- **Chrome extension** (extension/): one click sends the rendered page text straight to the server. Works on Reddit, LinkedIn, and anything your logged-in browser can see.
- **Fixes:** Groq fallback was silently broken twice over (llama3-8b-8192 decommissioned; Groq 403s the default Python urllib user agent). Both fixed and verified.

### What Was New in v0.1 (April 2026)

- Replaced regex-based HTML extraction with trafilatura. Summaries are significantly cleaner and more accurate.
- Added fetch failure guard: if a URL cannot be extracted, the LLM is not called and you get a clear notification instead of a garbage summary.
- Fixed persistent delete: clicking X removes the item from knowledge.json permanently, not just from the page view.
- Added auth token to the iPhone receiver endpoint. The iOS shortcut must send the correct Bearer token or the request is rejected.

---

## Stack

- Python 3.14, rumps, trafilatura
- LM Studio running Qwen 2.5 14B Instruct at localhost:1234
- iOS Shortcuts for iPhone share sheet integration
- Plain JSON storage, plain HTML knowledge base

---

## Setup

### Mac Menu Bar App

1. Clone this repo: `git clone https://github.com/ShashankKarpal/content-digest-app.git`
2. Install dependencies: `/opt/homebrew/bin/python3 -m pip install rumps trafilatura --break-system-packages`
3. Run LM Studio and load Qwen 2.5 14B Instruct. Start the local server on port 1234.
4. Run the app: `/opt/homebrew/bin/python3 ~/content-digest-app/app.py`

### iPhone Share Extension

1. Open the Shortcuts app on iPhone.
2. Create a new shortcut called "Save to Content Digest".
3. Add a "Get Contents of URL" action:
   - URL: `http://YOUR_MAC_IP:7778/add`
   - Method: POST
   - Headers: `Authorization: Bearer YOUR_AUTH_TOKEN`
   - Body: JSON with key `url` and value set to the shared URL.
4. Add the shortcut to your share sheet.

Replace YOUR_MAC_IP with your Mac's local IP (System Settings, Wi-Fi, Details).
Replace YOUR_AUTH_TOKEN with the value of AUTH_TOKEN in app.py line 22.

---

## Roadmap

| Version | Goal | Status |
|---|---|---|
| v0.1 | Frictionless capture and trustworthy summaries | In progress |
| v0.2 | Return loop: digest email and item states | Planned |
| v0.3 | Reduce overload: grouping, ranking, suppress clutter | Planned |
| v1 | Thoughtful assistant: personalization and patterns | Planned |

---

## Chrome Extension Setup

1. Open chrome://extensions, enable Developer mode.
2. Load unpacked, select ~/content-digest-app/extension.
3. Open the extension options, set your server URL and auth token (from secrets.json).
4. Click the pin on any page (or right-click, Save to Content Digest). The rendered page text is captured browser-side, so blocked-to-servers sites like Reddit and LinkedIn work.

## Server Dependencies (M1)

- `pip3 install trafilatura youtube-transcript-api --break-system-packages`
- `ollama pull nomic-embed-text` (optional, enables semantic ask; falls back to keyword search without it)

## Known Limitations

- Ollama (or the Groq fallback) must be reachable for summarization to work.
- Mac IP may change on different networks. Update the iPhone shortcut if it stops working.
- YouTube videos without transcripts fall back to the fetch failure guard rather than guessing from the title.
- LinkedIn saved posts harvesting is planned but not yet built (the Chrome extension covers individual LinkedIn pages).
