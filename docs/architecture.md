# docs/architecture.md

## System Architecture — Content Digest App (v0.1)

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
- Endpoint: POST to http://192.168.1.61:7778/add
- Accepts JSON payload with URL from iOS Shortcuts.
- iOS Shortcut named "Save to Content Digest" appears in share sheet of any app.
- Mac IP: 192.168.1.61 (may change, update shortcut if it stops working).
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
- Mac IP (192.168.1.61) may change. iPhone shortcut must be updated manually if it does.
- Python at /opt/homebrew/bin/python3 (version 3.14).
- User edits files via Terminal heredoc or python3 -c, not TextEdit (causes indentation issues).
