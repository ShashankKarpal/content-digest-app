# docs/roadmap.md

## Roadmap — Content Digest App

Each version proves one behavior. Not one feature. One behavior.

---

## v0.1 — Prove People Save
**Behavior to prove:** Users save content regularly and trust the summaries.

Priorities:
- Frictionless capture from Mac menu bar and iPhone share sheet.
- Clean content extraction via trafilatura (replace regex).
- Trustworthy 150-200 word summaries with action pointers.
- Persistent delete, no data loss.
- Basic deduplication.
- Security: localhost binding.

Done when: user saves at least 5 items in the first week without friction, and summaries feel useful across varied content types.

---

## v0.2 — Prove People Return
**Behavior to prove:** Users come back to their saved content on a rhythm.

Priorities:
- Digest email every 3-4 days at 7am via Python smtplib and Gmail. No third-party services.
- Email format: grouped by category, title, summary, action pointer, item state tag.
- Item states: act on this, revisit later, archive. Stored in knowledge.json. Reflected in UI.
- Review flow in knowledge.html: user can change item state directly.

Done when: user opens digest email and interacts with at least one item per cycle.

---

## v0.3 — Prove People Act
**Behavior to prove:** Users take action on saved content. The backlog does not become a pile to ignore.

Priorities:
- Group similar saves together (topic clustering).
- Surface the few items most worth attention based on recency, category, and engagement signals.
- Suppress or visually demote low-value clutter.
- Highlight items marked act on this prominently.

Done when: user does not feel overwhelmed by backlog and regularly archives or acts on items.

---

## v1 — Feel Like a Thoughtful Assistant
**Behavior to prove:** The app understands what the user actually cares about.

Priorities:
- Notice patterns in what the user acts on vs. archives.
- Personalize what gets surfaced in digests and the knowledge base.
- Possibly: custom digest frequency per category.
- Possibly: weekly summary of actions taken (you acted on 3 DevOps items this week).

Done when: user feels the app is working for them, not just collecting for them.

---

## Parking Lot (No Version Assigned Yet)

- LinkedIn saved posts harvesting from linkedin.com/my-items/saved-posts.
- Reddit integration via OAuth (blocked on API approval for content-digest app).
- Mobile-friendly knowledge base view.
- Export to Notion or Obsidian.
- Multi-user or shared digest (Karl's use case, not yet scoped).

---

## Rule

Do not pull parking lot items into an active version unless the current behavior has been proved and signed off. Each version gets Karl's review before the next begins.
