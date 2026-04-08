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

## Current Version: v0.1

**Goal:** Frictionless capture and trustworthy summaries.

### What Is New in v0.1 (April 2026)

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

## Known Limitations

- LM Studio must be running for summarization to work.
- Mac IP may change on different networks. Update the iPhone shortcut if it stops working.
- Reddit integration is pending API approval.
- LinkedIn saved posts harvesting is planned but not yet built.
