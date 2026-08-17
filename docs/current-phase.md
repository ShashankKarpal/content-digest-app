# docs/current-phase.md

## Current Version: v0.4 (shipped in code 2026-07-19; deploy to M1 pending)

## What We Are Proving Now

People return and act. Item states (act / revisit / archive) plus the ask box are live; the test is whether they get used: does the user set states from the morning brief, and does the archive pile shrink? Reddit capture is no longer a gap; every major source now summarizes through the same pipeline.

Exit criteria for this phase: user sets a state on at least one item per digest cycle, and asks the knowledge base at least once a week without being prompted.

---

## Historical: v0.1 phase definition below (kept for reference)

## What We Were Proving

People will save. Capture is frictionless enough to become a habit. Summaries are trustworthy enough to feel useful.

If saving is even slightly annoying, or summaries feel noisy or generic, the habit never forms. v0.1 has to nail both of these before anything else is built.

---

## What Is In Scope for v0.1

- Frictionless capture from Mac (menu bar dialog) and iPhone (Shortcuts share sheet via POST to port 7778).
- Clean content extraction: replace regex with trafilatura for proper HTML parsing.
- Trustworthy 150-200 word summaries with action pointers via LM Studio (Qwen 2.5 14B).
- Reliable storage to knowledge.json without data loss or corruption.
- Persistent delete: delete actions must remove items from knowledge.json, not just from the UI.
- Basic deduplication: same URL should not be saved twice.
- Security: receiver should bind to localhost, not 0.0.0.0.
- Stable auto-start via LaunchAgent.

---

## What Is Explicitly Out of Scope for v0.1

- Digest email (v0.2).
- Item states: act on this, revisit later, archive (v0.2).
- Grouping or ranking saves by importance (v0.3).
- Personalization or behavioral patterns (v1).
- LinkedIn saved posts harvesting (future, not assigned to a version yet).
- Reddit integration (blocked on API approval, not a v0.1 dependency).
- Any UI redesign beyond fixing known bugs.

---

## Why This Scope

If v0.1 is not solid, every version built on top of it inherits its fragility. A leaky capture loop, noisy summaries, and broken deletes will make the digest (v0.2) feel unreliable before it even launches. Fix the foundation first.

---

## v0.1 Completion Criteria

- [ ] trafilatura replaces regex for content extraction.
- [ ] Delete is persistent: item removed from knowledge.json when deleted.
- [ ] Receiver binds to localhost, not 0.0.0.0.
- [ ] 10 varied URLs tested: articles, LinkedIn, YouTube, Reddit. Summaries feel useful.
- [ ] iPhone shortcut tested end to end and working reliably.
- [ ] No duplicate saves for the same URL.
- [ ] Karl reviews and signs off.
