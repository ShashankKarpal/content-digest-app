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

## Next (v0.2, do not start until v0.1 is signed off)

- [ ] Build digest email: compile knowledge.json every 3-4 days at 7am via Python smtplib and Gmail.
- [ ] Email format: grouped by category, title, summary, action pointer, item state tag.
- [ ] Add item states to knowledge.json: act on this, revisit later, archive.
- [ ] Add item state controls to knowledge.html UI.
- [ ] Scheduled trigger: launchd or cron on Mac.

## Later (v0.3 and beyond)

- [ ] Group similar saves together (topic clustering).
- [ ] Surface most important items first in digest and knowledge base.
- [ ] Suppress or demote low-value clutter.
- [ ] Validate LLM output before saving: JSON shape, category values, relevance bounds.
- [ ] Move hardcoded values into a config file.
- [ ] Normalize URLs before dedup: strip tracking params.
- [ ] Add concurrency protection for knowledge.json writes.

## Parking Lot (no version assigned)

- [ ] LinkedIn saved posts harvesting.
- [ ] Reddit OAuth integration (pending API approval).
- [ ] Mobile-friendly knowledge base view.
- [ ] Export to Notion or Obsidian.
