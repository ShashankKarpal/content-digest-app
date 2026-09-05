# docs/current-phase.md

## Current Version: v0.5 (shipped 2026-08-17; extension 0.6.1 and the measurement instruments 2026-09-05)

## What We Are Proving Now

The loop closes. v0.5 put the whole return-and-act path in place: the morning
brief resurfaces three backlog items with one-tap Act / Later / Archive links,
the knowledge base has a triage deck, and untouched items decay into the
archive on their own. The question is whether the user acts or archives by
hand at all now that the machinery exists.

This is a MEASUREMENT PHASE, from 2026-08-17 to about 2026-09-17. Nothing is
built that adds product surface until the read. Two things were allowed in as
instruments, not features (2026-09-05): the weekly loop check (every state
change dated and attributed to its surface, a row per week written on the host)
and the runtime watchdog (heartbeat, client contact, host-health line, the Mac
client as observer), because without them the read cannot tell a quiet week
from a dead capture path.

Exit criteria for this phase: the user sets a state on at least one item per
digest cycle, and asks the knowledge base at least once a week without being
prompted. Measured by `loopcheck-history.txt` on the host (baseline
2026-08-17: act 0, manual archive 0, later 2, 116 auto-archived) with the
known outage windows subtracted (menu bar client down 08-16 to 08-24, phone off
the private network 08-26 to 08-28, host offline 08-31).

Pivot clause (red team audit 2026-08-17, section 6): if act and manual archive
are still near zero on clean days when the window closes, the product pivots
to a capture-to-expiring-digest pipe with no knowledge base. Parked until the
read, in this order if the loop shows life: save-to-digest MCP, off-tailnet
triage, push channel, host failover.

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
