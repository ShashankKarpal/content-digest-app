# docs/todo.md

## Task List — Content Digest App

## Must-Have (v0.1)

- [x] Run Karl's full audit on app.py and review findings.
- [x] Replace regex-based HTML extraction with trafilatura.
- [x] Fix delete persistence: deletion removes item from knowledge.json, not just UI.
- [x] Add auth token to receiver: requests without Bearer token are rejected.
- [x] Push markdown OS files to GitHub.
- [ ] Test 10 varied URLs: articles, LinkedIn, YouTube, Reddit, news. Summaries must feel trustworthy.
- [ ] Test iPhone shortcut end to end across Safari, LinkedIn, Chrome.
- [ ] Confirm no duplicate saves for the same URL.
- [ ] Karl review and sign-off on v0.1.

## Done in v0.4 (2026-07-19)

- [x] Reddit summaries without API approval: old.reddit HTML + arctic-shift fallback (extractors.py).
- [x] Source-aware extractors: YouTube transcripts, X posts.
- [x] Add item states to knowledge.json: act on this, revisit later, archive.
- [x] Add item state controls to knowledge.html UI + state pills in daily brief.
- [x] Validate LLM output before saving: JSON shape, category values, relevance bounds.
- [x] Normalize URLs before dedup: strip tracking params.
- [x] Auto-retry fetch failures + inbox reconciliation (every 6h).
- [x] Ask-your-knowledge-base: embeddings + keyword fallback, cited answers.
- [x] Chrome extension: browser-side capture with content passthrough.
- [x] Fix Groq fallback (decommissioned model + UA block).
- [x] Digest email (shipped earlier as daily_brief.py, 7am LaunchAgent).

## Deploy (next session, M1)

- [ ] git pull on M1; pip3 install youtube-transcript-api --break-system-packages.
- [ ] ollama pull nomic-embed-text (enables semantic ask).
- [ ] Restart server LaunchAgent; sanity test Reddit save, /state, /ask.
- [ ] Load extension/ in Chrome, set server + token in options.
- [ ] Verify morning brief shows state pills on the next real send.

## Later (v0.3 behaviors and beyond)

- [ ] Group similar saves together (topic clustering; embeddings now exist to power this).
- [ ] Surface most important items first in digest and knowledge base.
- [ ] Suppress or demote low-value clutter.
- [ ] Move hardcoded values into a config file.

## Parking Lot (no version assigned)

- [ ] LinkedIn saved posts bulk harvesting.
- [ ] Mobile-friendly knowledge base view.
- [ ] Export to Notion or Obsidian.
- [ ] Personalization from state patterns (v1).
