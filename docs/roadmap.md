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

## Delivered in v0.4 (2026-07-19, owner-directed bundle)

- Reddit summaries via old.reddit.com HTML + arctic-shift fallback (no API approval; the official API closed to new apps Nov 2025).
- Source-aware extractor registry: Reddit, YouTube transcripts, X posts.
- Item states (act / revisit / archive) in storage, UI, and morning brief.
- URL normalization before dedup; LLM output validation before save.
- Auto-retry of fetch failures + inbox reconciliation.
- Ask-your-knowledge-base: local embeddings with keyword fallback, cited answers.
- Chrome extension for browser-side capture (extension/): covers Reddit, LinkedIn, and any rendered page.

---

## Delivered in v0.5 (2026-08-17, red-team-audit-directed; see redteam-audit-2026-08-17.md)

- Auth on every endpoint: bearer token or session cookie on all POSTs, token-gated /view with in-page PWA unlock, trusted-source guard, placeholder tokens rejected.
- Resurfacing brief: up to 3 backlog items per morning email (pure-arithmetic scorer: age x relevance, act first, category-diverse, 5-day cooldown) with HMAC-signed one-tap Act/Later/Archive links (72h expiry, GET /triage).
- Auto-archive decay: News 7d TTL, default 21d, or 3 ignored resurfacings; reversible, stamped, reported in the brief.
- Triage deck on /view: one card at a time, keyboard a/l/x/space, max 10 cards, completion state. Shares the brief's scorer and fatigue ledger.
- Repo truth pass: legacy app.py deleted, requirements.txt added, docs/ published.

---

## Killed (red team audit 2026-08-17; do not resurrect without new evidence)

- Topic clustering: organizes the pile instead of draining it.
- LinkedIn saved-posts bulk harvesting: more input into the loop's narrow end.
- Export to Notion or Obsidian: concedes the loop cannot close here.
- Multi-user or shared digest: single-user product, one maintainer.
- Mobile-friendly KB view: already shipped as the PWA (removed as redundant).

## Parking Lot (No Version Assigned Yet)

- Personalization from state patterns (v1 direction: what gets acted on vs archived). Data-gated: requires weeks of real act/archive signal from the v0.5 loop before it is buildable at all.
- Native Swift menu bar client (deferred by the audit: multi-session build; revisit as the v1 flagship once the loop is proven in use).

---

## Rule

Do not pull parking lot items into an active version unless the current behavior has been proved.
