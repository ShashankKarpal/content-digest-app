# CLAUDE.md
# Root Instruction File — Content Digest App

## Read This First, Every Session

Before doing any substantial work, read these files in order:

1. CLAUDE.md (this file)
2. docs/product-intent.md
3. docs/current-phase.md
4. docs/session-handoff.md
5. docs/todo.md

Do not skip this. Do not rely on memory from a previous session. Read the files.

---

## What This Product Is

A tool that solves saved-content hoarding. Not a link saver. Not a read-later app.

The core user loop is:

**capture -> summarize -> resurface -> review -> act or archive**

Every change must be judged by whether it strengthens one of these three things:

- **Capture:** Is saving faster, more reliable, and more frictionless?
- **Return and review:** Is the user coming back to their saved content?
- **Action and archive:** Is the user doing something because of what they saved?

If a proposed change does not strengthen one of these, say so explicitly before proceeding.

---

## Version Boundaries

### v0.1 — Prove people save
Goal: frictionless capture and trustworthy summaries.
Do not expand scope unless it directly improves capture reliability or summary quality.

### v0.2 — Prove people return
Goal: build the return loop.
Priorities: digest email, item states (act on this, revisit later, archive), review flow.

### v0.3 — Prove people act
Goal: reduce overload, surface what matters.
Priorities: grouping similar saves, ranking by importance, suppressing low-value clutter.

### v1 — Make it feel like a thoughtful assistant
Goal: personalization.
Priorities: notice patterns in what the user acts on, surface content based on behavior.

---

## Development Principles

- Prefer the smallest change that proves the next user behavior.
- Work in tiny steps. Each step should be testable before moving on.
- Do not add speculative systems or abstractions without a clear immediate need.
- Preserve existing working behavior unless a change is explicitly required.
- Separate product risks from code-quality improvements. Flag both.
- Distinguish must-have, nice-to-have, and later for every proposed task.
- Do not jump straight into coding if the task appears to solve the wrong product problem.

---

## Operating Rules

- Update docs/session-handoff.md at the end of every meaningful session.
- Update docs/decision-log.md when a real decision is made.
- Update docs/architecture.md if the implementation meaningfully changes system shape.
- Append to docs/worklog.md after major work with a dated note.
- Do not overbuild. Do not drift from the core loop.
- If unsure whether a change is in scope for the current phase, check docs/current-phase.md before proceeding.

---

## Response Format for Substantial Tasks

1. Restate the goal.
2. Explain the proposed approach.
3. Name the files to change.
4. Implement or draft the changes.
5. List risks, gaps, and next steps.

Do not jump straight into code if the task appears to solve the wrong product problem.
