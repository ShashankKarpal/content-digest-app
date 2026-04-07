# docs/decision-log.md

## Decision Log — Content Digest App

Format: Date | Context | Decision | Reason

---

## 2026-04-07 | Content Extraction | Replace regex with trafilatura
Context: App currently uses regex to strip HTML before passing content to LM Studio. Karl flagged this as the most urgent technical fix. Regex is brute-force, pulls garbage characters and navigation clutter, and produces noisy LLM input.
Decision: Replace regex-based extraction with trafilatura before continuing any other feature development.
Reason: Noisy LLM input degrades summary quality for every single save. This is foundational to v0.1's goal of trustworthy summaries. Fixing it later means every summary produced before the fix is lower quality.

---

## 2026-04-07 | Delete Behavior | Fix delete to persist to knowledge.json
Context: Current delete action removes the visible item from knowledge.html but does not write the deletion back to knowledge.json. Items accumulate invisibly in storage.
Decision: Delete must remove the item from knowledge.json and regenerate knowledge.html. UI deletion alone is not acceptable.
Reason: Silent data accumulation will corrupt future features. Digest email and item states in v0.2 will surface deleted items if storage is not clean.

---

## 2026-04-07 | Security | Bind receiver to localhost instead of 0.0.0.0
Context: The iPhone receiver endpoint is currently exposed on 0.0.0.0, making it reachable from any device on the local network. Karl flagged this as an unnecessary risk, even in a local setup.
Decision: Bind receiver to localhost or add a simple auth token.
Reason: Reduces attack surface for prompt injection and unauthorized saves. Easy fix with no downside.

---

## 2026-04-07 | Development Process | Adopt repo-local markdown OS for persistent Claude session memory
Context: App is being built across many Claude sessions with no coding background. Each session required re-explaining full context. Karl recommended a structured markdown filesystem inside the repo.
Decision: Create CLAUDE.md and docs/ folder as the persistent memory and operating system for all future development sessions.
Reason: Prevents context drift, reduces re-explanation overhead, enables Karl to review and contribute via GitHub without needing a call to understand current state.

---

## 2026-04-07 | Version Strategy | One behavior per version, not one feature
Context: Original plan was to add features incrementally (digest email next). Karl reframed this as proving user behaviors, not shipping features.
Decision: v0.1 proves people save. v0.2 proves people return. v0.3 proves people act. v1 proves personalization works.
Reason: Each version has a testable behavior as its exit criterion. This prevents scope creep, makes progress legible, and ensures each version is useful before the next begins.

---

## 2026-04-07 | GitHub Workflow | Use GitHub Desktop instead of CLI for pushes
Context: User has no coding background and finds CLI git commands unfamiliar.
Decision: Use GitHub Desktop app for all commits and pushes. Local repo at ~/content-digest-app linked to https://github.com/ShashankKarpal/content-digest-app.git.
Reason: Lower friction means more consistent commits. Karl can review, branch, and submit changes for merge via GitHub.
