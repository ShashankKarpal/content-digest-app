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

## 2026-07-19 | Reddit Access | old.reddit.com HTML primary, arctic-shift archive fallback
Context: Reddit Data API approval was pending since March. Live research confirmed Reddit closed self-serve API access on 2025-11-11 (Responsible Builder Policy) and killed unauthenticated .json endpoints in Dec 2025. Approval was never coming.
Decision: Fetch threads from old.reddit.com HTML (verified 200 from residential IP, ~100 req/10 min) with the arctic-shift archive API as automatic fallback. Both feed the unchanged summarization path. The r.jina.ai fallback is skipped for Reddit (Jina IPs are blocked by Reddit).
Reason: First-party, verified working, zero new dependencies, and negligible practical risk at single-user volume. Waiting for API approval is a dead end by policy.

---

## 2026-07-19 | Version Strategy | v0.4 bundles v0.2 return loop plus hygiene and search, owner-directed
Context: Owner reviewed the strategic brief and directed shipping Reddit support plus all five proposed features in one pass, overriding the one-behavior-per-version cadence for this release.
Decision: v0.4 ships: Reddit + extractor registry, item states + review loop, URL normalization + dedup + output validation, auto-retry + inbox reconciliation, semantic ask, Chrome extension capture.
Reason: Explicit owner decision with blanket approval; features were already validated as the next steps in the roadmap.

---

## 2026-07-19 | Capture Strategy | Browser-side capture extension replaces server-only fetching for blocked sites
Context: Reddit, LinkedIn, and a growing set of sites block server-side fetches. The original content-digest extension (fork of sunlesshalo/reddit-tab-harvester) was blocked by Reddit 403s.
Decision: Rebuild the extension inside this repo (extension/) as a generic capture layer: it sends the rendered page text to /add, and the server skips fetching when content is provided.
Reason: A logged-in human browser on a residential IP cannot be blocked server-side. One mechanism covers Reddit, LinkedIn, and every future walled site.

---

## 2026-07-19 | Dedup | Canonical URL identity per source, not just tracking-param stripping
Context: The same Reddit thread saved twice: once via full URL, once via the opaque iOS /s/ share link. Param stripping cannot see that two different URLs are the same content.
Decision: normalize_url now assigns one canonical identity per known source: Reddit threads collapse to https://www.reddit.com/r/SUB/comments/ID/ (share and redd.it links resolved first, cached), YouTube to watch?v=ID, twitter.com to x.com. LinkedIn tracking params (rcm, trk) added. One-time migration canonicalized all stored URLs, merged 1 duplicate, pruned orphan embeddings (101 items, 101 vectors).
Reason: Dedup must key on content identity, not URL spelling. Share sheets produce aliases constantly; iOS Reddit always shares /s/ links.

---

## 2026-07-19 | AI Fallback | Groq model and user agent fixed
Context: End-to-end testing revealed the Groq fallback was silently broken twice: llama3-8b-8192 was decommissioned by Groq, and Groq's edge 403s the default Python-urllib user agent.
Decision: GROQ_MODEL is now llama-3.1-8b-instant and all Groq requests send a custom User-Agent.
Reason: Verified live: old model returns model_decommissioned, default UA returns 403, custom UA returns 200.

---

## 2026-04-07 | GitHub Workflow | Use GitHub Desktop instead of CLI for pushes
Context: User has no coding background and finds CLI git commands unfamiliar.
Decision: Use GitHub Desktop app for all commits and pushes. Local repo at ~/content-digest-app linked to https://github.com/ShashankKarpal/content-digest-app.git.
Reason: Lower friction means more consistent commits. Karl can review, branch, and submit changes for merge via GitHub.
