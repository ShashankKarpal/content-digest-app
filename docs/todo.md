# docs/todo.md

## Task List — Content Digest App

---

## Must-Have (v0.1, do these before anything else)

- [ ] Run Karl's full audit prompt on app.py and review findings.
- [ ] Replace regex-based HTML extraction with trafilatura.
- [ ] Fix delete persistence: deletion must remove item from knowledge.json, not just from UI.
- [ ] Bind receiver to localhost instead of 0.0.0.0 (security fix).
- [ ] Test 10 varied URLs after trafilatura fix: articles, LinkedIn, YouTube, Reddit, news. Summaries must feel trustworthy.
- [ ] Test iPhone shortcut end to end: share from Safari, LinkedIn, Chrome. Confirm URL reaches app and summary is generated.
- [ ] Confirm no duplicate saves for the same URL.
- [ ] Push markdown OS files to GitHub.
- [ ] Karl review and sign-off on v0.1.

---

## Next (v0.2, do not start until v0.1 is signed off)

- [ ] Build digest email: compile knowledge.json every 3-4 days at 7am, send via Python smtplib with Gmail.
- [ ] Email format: grouped by category, title, summary, action pointer, item state tag.
- [ ] Add item states to knowledge.json schema: act on this, revisit later, archive.
- [ ] Add item state controls to knowledge.html UI.
- [ ] Scheduled trigger for digest: launchd or cron on Mac.

---

## Later (v0.3 and beyond, do not scope until v0.2 is proved)

- [ ] Group similar saves together (topic clustering).
- [ ] Surface most important items first in digest and knowledge base.
- [ ] Suppress or demote low-value clutter.
- [ ] Validate LLM output before saving: JSON shape, category values, relevance bounds.
- [ ] Move hardcoded values (model name, port, paths) into a config file.
- [ ] Sanitize HTML output against LLM-generated and URL-influenced fields.
- [ ] Add concurrency protection for knowledge.json writes.

---

## Parking Lot (no version assigned)

- [ ] LinkedIn saved posts harvesting from linkedin.com/my-items/saved-posts.
- [ ] Reddit OAuth integration (blocked on API approval for "content-digest" app).
- [ ] Mobile-friendly knowledge base view.
- [ ] Export to Notion or Obsidian.
