# Content Digest App: Red Team Audit and Top 5 Feature Decision

Date: 2026-08-17. Account: kk2 (identity verified via bridge brief, org id redacted). Run type: read-only hostile audit. Repo: content-digest-app (local working copy), remote ShashankKarpal/content-digest-app (public, MIT).

Confidence labels: VERIFIED (read in a file or command output), INFERRED (reasoned from evidence), UNVERIFIED (cannot confirm from this machine). Every claim carries its source.

Bridge context: no handoff for this project has ever existed (`bridge.py brief --as kk2 --project content-digest-app`: "none exists yet", VERIFIED). No kk2 session log mentions this repo; all four prior session logs on it are kk1 (`grep -ril content-digest _claude-chats/`, VERIFIED). kk2 has never touched this repo before this audit (INFERRED from the absence of any kk2 trace). Backup health: ok, last success 4h before this run (bridge brief output, VERIFIED).

---

## 1. Repo forensics summary

| Fact | Value | Confidence | Source |
|---|---|---|---|
| Last commit | 77c28b6, 2026-08-03 11:30 +0530, Shashank Karpal, "ci: gitleaks-action v3 and checkout v6 for Node 24, add workflow_dispatch" | VERIFIED | `git -C <repo> log -1` |
| Dormancy | 14 days since last commit, not months | VERIFIED | same |
| Total commits | 37, single author, first commit 2026-04-07 | VERIFIED | `git rev-list --count HEAD`, `git log --reverse` |
| Cadence, 90 days | 2026-06: 11, 2026-07: 10, 2026-08: 6 | VERIFIED | `git log --since="90 days ago"` |
| Cadence, 12 months | 2026-04: 10, 2026-05: 0, 2026-06: 11, 2026-07: 10, 2026-08: 6 | VERIFIED | `git log --since="12 months ago"` |
| Branch | main only, tracking origin/main, HEAD == origin/main (77c28b6 both) | VERIFIED | `git branch -a`, `git rev-parse` |
| Working tree | clean, zero uncommitted, zero untracked-and-unignored | VERIFIED | `git status --porcelain` |
| Stashes | 0 | VERIFIED | `git stash list` |
| Stale branches | none local, none remote beyond main | VERIFIED | `git branch -a` |
| WIP commits | none (no wip/temp/fixup subjects in log) | VERIFIED | commit subject scan |
| TODO/FIXME/HACK/XXX markers | 0 across all .py, .js, .html | VERIFIED | `grep -rn -E "TODO\|FIXME\|HACK\|XXX"` |
| Dead code | app.py (420 lines, full legacy pipeline superseded by server.py + client.py); app.py.backup; config.json.save; test_fix_verification.py (self-labelled "Delete this file after verification", test_fix_verification.py:50) | VERIFIED | file reads |
| Package manifest | none. No requirements.txt, no pyproject | VERIFIED | file listing |
| Local data files | stale relics: knowledge.json mtime Jun 12 (37 items, zero state fields set), daily_brief.log last entry 2026-06-12, error.log last write Jul 30 ("Address already in use" from a local run attempt) | VERIFIED | file mtimes, JSON parse, log tail |
| Live production | M1 server up, HTTP 200 on /view; 144 items, last save 2026-08-17 05:14, the morning of this audit | VERIFIED | `curl http://<m1-tailnet-ip>:7778/view` |
| Plaintext credential in tree | config.json holds a plaintext SMTP credential (gitignored, not tracked, but sitting in a folder that syncs to the M1 nightly) | VERIFIED | `cat config.json`, .gitignore |

The "dormant" framing in the task brief is half right. The repo is dormant (14 days, and the last three commits were CI and README, not product). The product is not dormant: 18 saves in August, one this morning. Code development stopped; usage did not.

---

## 2. Ground-truth state map: the full loop

The path anchor matters before the table: server.py:17 sets `BASE_DIR = Path.home() / "content-digest-app"`. That directory does not exist on the M4 (VERIFIED, `ls`). All runtime truth lives on the M1 at `~/content-digest-app`. Every data file inside this repo folder is a pre-consolidation relic. daily_brief.py:17 anchors to `Path(__file__).parent` instead, so the two entry points disagree about where data lives; on the M1 they happen to coincide, on the M4 they diverge silently.

| Loop link | Status | Evidence | Confidence |
|---|---|---|---|
| Source ingestion (menu bar, iPhone shortcut, Chrome extension, inbox-before-auth) | SHIPS TODAY | server.py:1151-1237 (/add, /add_sync, inbox capture before auth); client.py running as LaunchAgent com.shashank.contentdigest.client, PID live (`launchctl list`); live save stamped 2026-08-17 05:14 | VERIFIED |
| Extraction (Reddit, YouTube, X, LinkedIn, generic trafilatura, reader-proxy fallback, 3-layer junk gates) | SHIPS TODAY | extractors.py:461 get_extractor registry; server.py:52-160 gates; live failures list shows "quality" rejections actually firing | VERIFIED |
| Deduplication (canonical URL identity per source, short-link resolution) | SHIPS TODAY | extractors.py:85 normalize_url, :136 _canonical_reddit; server.py:576-579 skip-if-saved | VERIFIED |
| Storage (knowledge.json, atomic tmp+rename, embeddings.json) | SHIPS TODAY | server.py:186-189 _save_data; 144 live items | VERIFIED |
| Summarisation (Ollama qwen2.5:3b on M1, Groq cloud fallback) | SHIPS TODAY | server.py:162-169, 282-333; every live item carries summary + action_points | VERIFIED |
| Summarisation via LM Studio | DECLARED ONLY | README.md:68 and :75 claim "Ollama or LM Studio"; the code calls only the Ollama API at :11434 (server.py:162, app.py:27). LM Studio's OpenAI-compatible endpoint at :1234 appears nowhere in live code, only in the historical section of architecture.md:59-64 | VERIFIED |
| Ranking (surface the few items most worth attention) | DECLARED ONLY | roadmap.md:42 declares it for v0.3; the only ranking in code is a client-side sort dropdown on a model-self-assigned 1-5 relevance number (server.py:831-835, :922-924). No scorer, no engagement signal, nothing decides what deserves attention | VERIFIED |
| Surfacing / resurfacing (the return rhythm) | HALF-BUILT | daily_brief.py:47-65 filter_last_24h: the brief only ever contains items saved in the last 24 hours. Nothing in the codebase ever brings an old item back in front of the user. The /view page defaults to newest-first over the whole pile (server.py:922) | VERIFIED |
| Review / act / archive (item states) | HALF-BUILT: mechanism ships, behavior is dead | Code complete: /state endpoint server.py:1207, UI buttons :940-944, brief pills daily_brief.py:166-175. Live data: 144 items, states are 142 empty, 2 revisit, 0 act, 0 archive, across four months of use | VERIFIED |
| Ask-your-KB (embeddings + cited answers) | SHIPS TODAY (usage unknown) | server.py:438-483, :1214-1221; nomic-embed-text backfill code :416-435. Whether it gets asked weekly is not evidenced anywhere | VERIFIED code, UNVERIFIED usage |
| Daily brief delivery | SHIPS TODAY on the M1 (INFERRED) | INFRA.md:31 lists "daily brief" among M1-owned services. The only readable log is the stale local one (last line 2026-06-12, "Sent brief with 0 items"). No M1 log is visible from this machine | INFERRED, delivery UNVERIFIED |

### The broken link, named

**Resurfacing.** Capture, extraction, dedupe, storage, and summarisation all work and are used daily. The loop breaks at the exact point the product was built for: nothing ever resurfaces an old item, so review never happens, so act/archive never happens. The daily brief is a mirror of yesterday, not a hand reaching into the backlog. The result is measurable: 144 items, 0 acted, 0 archived, 2 revisit in four months (VERIFIED, live /view data). CLAUDE.md:22 defines the loop as "capture -> summarize -> resurface -> review -> act or archive". The first two links are industrial grade. The third link does not exist, and the last two starve because of it. This is precisely the ADHD backlog guilt pile the product-intent doc swears it exists to kill (product-intent.md:5-7), now reproduced inside the tool that was meant to prevent it.

---

## 3. Previously decided roadmap, quoted verbatim

### v0.3 "Prove People Act" (decided 2026-04-07 per decision-log.md:37-40 and worklog.md:47-62)

docs/roadmap.md:41-45:
> - Group similar saves together (topic clustering).
> - Surface the few items most worth attention based on recency, category, and engagement signals.
> - Suppress or visually demote low-value clutter.
> - Highlight items marked act on this prominently.

### v1 "Feel Like a Thoughtful Assistant" (decided 2026-04-07, same source)

docs/roadmap.md:54-58:
> - Notice patterns in what the user acts on vs. archives.
> - Personalize what gets surfaced in digests and the knowledge base.
> - Possibly: custom digest frequency per category.
> - Possibly: weekly summary of actions taken (you acted on 3 DevOps items this week).

README.md:176 (public commitment): `| v1 | Personalization: surface content based on what you act on | Planned |`

### Later list (docs/todo.md:41-44, dated to the 2026-07-19 v0.4 session per todo.md:17)

> - [ ] Group similar saves together (topic clustering; embeddings now exist to power this).
> - [ ] Surface most important items first in digest and knowledge base.
> - [ ] Suppress or demote low-value clutter.
> - [ ] Move hardcoded values into a config file.

### Parking lot (docs/roadmap.md:77-81, last touched 2026-07-19)

> - LinkedIn saved posts harvesting from linkedin.com/my-items/saved-posts (bulk; single pages covered by the extension).
> - Mobile-friendly knowledge base view.
> - Export to Notion or Obsidian.
> - Multi-user or shared digest (Karl's use case, not yet scoped).
> - Personalization from state patterns (v1 direction: what gets acted on vs archived).

### Next-up list (docs/STATE.md:44-46, written 2026-08-07 by the portfolio audit)

> 1. Decide issue #2 and implement split binding (small, high value).
> 2. Add requirements.txt so M1 rebuilds are deterministic.
> 3. Close out the v0.1 validation checklist or delete it from todo.md if superseded.

---

## 4. Red team pass 1: verdicts on the previous roadmap

**Topic clustering: KILL.** The todo.md phrasing convicts itself: "embeddings now exist to power this". That is a capability looking for a justification, the textbook definition of feature-shopping. The user does not open the pile; grouping an ignored pile into prettier sub-piles produces a better-organized ignored pile. Clustering serves a librarian. This user needs a bouncer.

**Surface the few items most worth attention: KEEP, as the core of everything.** This is the one v0.3 item aimed at the broken link, and it sat unbuilt for four months while a Chrome extension, a PWA manifest, brand lockups, and a menu bar icon all shipped. The build history optimized the working half of the loop and starved the broken half. The item survives, but "in digest and knowledge base" is too vague to build; it is rewritten in pass 2 as a concrete resurfacing brief.

**Suppress or demote low-value clutter: REWRITE.** As written it means CSS opacity on sad cards. The honest version is auto-archive: items nobody touched in N days leave the active view entirely, visibly and reversibly. Demotion preserves the guilt pile at 55 percent opacity; expiry deletes the guilt.

**Highlight items marked act on this prominently: KILL as decoration.** There are zero items marked act. Highlighting an empty set is a no-op shipped as a feature. If the resurfacing loop works, this falls out for free; if it does not, this is paint on a door that never opens.

**Move hardcoded values into a config file: DEFER.** Zero user behavior changes. Housekeeping bundled into a product roadmap is how sessions get spent without the product moving.

**v1 personalization (all four bullets, plus the README "Planned" row): KILL until data exists.** Personalization learns from act-vs-archive patterns. The live corpus contains two state actions, ever. There is nothing to learn from, and there will be nothing until resurfacing forces state decisions. The flagship v1 promise is currently unbuildable as a matter of arithmetic, and keeping it "Planned" in a public README is a commitment the data cannot cash. This was decided in April, before any usage data existed; the data has since voted, and it voted no.

**LinkedIn saved-posts bulk harvesting: KILL.** It pumps more volume into the intake of a system whose outlet is welded shut. 144 unprocessed items becomes 400. It is also the most fragile possible scrape target (authwall, DOM churn), which the 2026-07-31 junk-item outbreak (worklog.md:9-22) already demonstrated at single-page scale.

**Mobile-friendly knowledge base view: KILL as already shipped.** The PWA with viewport meta, manifest, and iPhone screenshots shipped in 4a1f1e7 on 2026-08-01 (README.md:148-150). A parking lot carrying items that already shipped is a parking lot nobody reads, which is itself a finding.

**Export to Notion or Obsidian: KILL.** The product thesis is closing loops. Exporting the pile to a second app is formally conceding the loop cannot close here, and every ADHD user knows exactly how the Notion graveyard story ends. Feature-shopping, and off-thesis.

**Multi-user or shared digest: KILL.** Single-user portfolio app, one maintainer, and issue #2 shows the security model is not ready for user number one, let alone user number two.

**STATE.md next-up (issue #2 split binding, requirements.txt): KEEP both.** Small, real, and the only items on any list that protect the data the loop depends on. They graduate to pass 2.

Feature-shopping roll call, named explicitly: topic clustering, export to Notion/Obsidian, multi-user digest, and the v1 personalization bundle in its current form. Each proposes a surface, none removes a friction.

---

## 5. Red team pass 2: candidates and scoring

Ten candidates: pass 1 survivors (rewritten) plus new proposals, then attacked. Scoring 0-2 per criterion. (a) survives a hostile senior reviewer, (b) reduces friction rather than adding a surface, (c) zero paid dependencies and full offline operation, (d) moves the WWDC 2027 craft bar, (e) ships in one focused build session, (f) maintainable by one person in six months.

| # | Candidate | a | b | c | d | e | f | Total |
|---|---|---|---|---|---|---|---|---|
| C1 | Resurfacing brief: 3 backlog items per morning email, with one-tap Act/Later/Archive links | 2 | 2 | 2 | 1 | 2 | 2 | 11 |
| C2 | Triage deck: one-card-at-a-time review mode in /view, keyboard-first, finite | 1 | 2 | 2 | 2 | 2 | 2 | 11 |
| C3 | Auto-archive decay: untouched items age out, visibly and reversibly | 2 | 2 | 2 | 1 | 2 | 2 | 11 |
| C4 | Security: auth on mutating endpoints, split binding (issue #2) | 2 | 1 | 2 | 1 | 2 | 2 | 10 |
| C5 | Repo truth pass: delete legacy app.py, add requirements.txt, fix README claims | 2 | 1 | 2 | 1 | 2 | 2 | 10 |
| C6 | Embedding-based resurfacing scorer (similarity to acted items + decay) | 1 | 2 | 2 | 1 | 1 | 1 | 8 |
| C7 | Ask-KB model upgrade to a larger local model | 1 | 1 | 2 | 0 | 2 | 2 | 8 |
| C8 | Native Swift/SwiftUI menu bar client | 1 | 1 | 2 | 2 | 0 | 1 | 7 |
| C9 | Weekly action recap email ("you acted on 3 items") | 0 | 1 | 2 | 0 | 2 | 2 | 7 |
| C10 | Topic clustering view (pass 1 corpse, re-scored to be fair) | 0 | 0 | 2 | 1 | 1 | 1 | 5 |

Attacks on my own shortlist:

**C1** is the highest-leverage build, but the hostile reviewer's question is "will you actually tap the links?" Honest answer: unknown, and that is the point. This is the cheapest possible experiment that can falsify the entire product thesis. If a 3-item email with one-tap buttons cannot get a state set, no feature can, and section 6 applies. The (d) score is 1, not 2: email HTML impresses no one at WWDC; the loop it closes does.

**C2**'s weakness is that a new view mode is technically "a surface". It survives because it replaces an infinite scroll (the single worst UI pattern for ADHD-C) with a finite deck that ends. The craft score is 2 because a polished, keyboard-driven, animated triage flow is exactly the kind of small-perfect interaction that reads as taste in a portfolio demo.

**C3**'s risk is silent data hiding. Mitigated: archived is a filter away, the brief reports "9 items aged out this week", and News gets a shorter TTL than Learning. The reviewer objection "you built a tool that throws my saves away" is answered by the live data: the alternative currently on display is a tool that keeps everything and surfaces nothing.

**C4** does not touch the loop, and pretending otherwise would be decoration-by-security. It is in the five because /delete, /state, and /ask are exempted from auth by server.py:1159 while the server binds 0.0.0.0 (server.py:1252): anyone on the LAN or tailnet can wipe every item with a curl loop. A portfolio app aimed at public scrutiny cannot ship a wipe-my-data endpoint with no auth. It also protects the state data that C1 through C3 exist to generate.

**C6** dies on cold start: 2 state actions is not a training signal. C1 ships with a plain heuristic (age, relevance, category diversity) and C6 becomes a drop-in upgrade the week real state data exists. **C7** improves answers to questions nobody is evidenced to ask. **C8** is real and probably the right WWDC 2027 move eventually, but it is a multi-session rewrite and fails (e) outright; it goes to the explicit non-scope list, not the trash. **C9** requires data that does not exist. **C10** stays dead.

### Local model requirements across candidates

The runtime host is the M1, not the M4. Summarisation runs qwen2.5:3b via Ollama on the M1 (server.py:165, local_settings.py points the M4 client at <m1-tailnet-ip>:11434, both VERIFIED); M1 RAM headroom is UNVERIFIED from this machine. C1 through C5 require **no new model**: the heuristic scorer is arithmetic, and embeddings, where used, are the already-deployed nomic-embed-text (about 0.5 GB resident). On the M4 dev machine, 48 GB fits all of this plus normal daily load with room for a future 14B q4 (about 9 GB) or 30B MoE (about 18 GB) summariser upgrade; no top-5 feature depends on that headroom. The Groq fallback (server.py:166-169) is a hosted cloud dependency that contradicts the local-only constraint; README.md:194 documents the opt-out (leave the key empty), and no proposed feature may depend on Groq. None does.

---

## 6. The existence question

**Does this app justify existing against a shell script plus a local model?**

Split the app in half. The knowledge-base half (JSON store, generated HTML, ask box) does not clear the bar: a 100-line script piping URLs through trafilatura into Ollama and appending to a JSON file replicates it in an afternoon, and a 3B model summarizing into a file nobody reopens is the same product with less CSS.

The capture half clears the bar decisively. iPhone share sheet to a durable inbox that survives auth failures, a Chrome extension that defeats authwalls by capturing the rendered DOM, per-source extractors with a verified Reddit strategy, canonical-URL dedupe across share-link aliases, three junk gates that turned a real production outbreak into visible retryable failures, and a 6-hour self-healing retry sweep. That is not a shell script; that was four months of adversarial hardening against real failures, each one logged in the worklog with the fix verified live.

So: **yes, it justifies existing, and the single feature that makes that true today is fire-and-forget multi-surface capture that never loses an input.** For an ADHD-C user, "the thought is captured before it evaporates, guaranteed, from any device" is the load-bearing feature, and it demonstrably works: a save landed at 05:14 the morning of this audit.

The uncomfortable corollary: capture is the feature that justifies the app **today**, but capture alone makes it a better Pocket, and product-intent.md:52 explicitly disowns that product ("Not a read-later app. Those solve storage, not action."). The feature that justifies the app **as designed** is the closed triage loop, which does not exist yet. C1 through C3 are the one-session-each bet that it can. If, after they ship, the state counts are still zero a month later, the honest move is the pivot: strip the knowledge base entirely and become a capture-to-expiring-digest pipe (save anything, get it in tomorrow's email once, auto-expire in 7 days, keep nothing). That product has no backlog by construction and would still be worth open-sourcing.

---

## 7. FINAL TOP 5 FEATURES, ranked

Step 9 check applied: features 1, 2, and 3 attack the broken resurfacing link directly; 4 protects the state data the loop generates; 5 is portfolio credibility. Nothing here decorates around the break.

### 1. Resurfacing brief with one-tap triage

The morning email stops mirroring yesterday and starts draining the backlog: exactly 3 resurfaced items per day (heuristic: staleness x relevance, category-diverse, act-marked first), each with three signed one-tap links (Act / Later / Archive) that set state without opening anything. Yesterday's saves collapse to a one-line count.
**Rationale:** the smallest possible build that makes review happen where the user already is (email), with a decision cost of one tap. It converts the brief from a report into the missing loop segment.
**Files:** daily_brief.py (selection + template), server.py (new GET /triage endpoint with HMAC-signed url+state+expiry token; reuse set_item_state at server.py:654).
**Model:** none. Optional nomic-embed-text for diversity, already deployed.
**Acceptance:** brief contains at most 3 resurfaced items; tapping a link sets state on the M1 and returns a tiny confirmation page; signed links expire in 72h; an item resurfaced 3 times with no response gets flagged for auto-archive (feeds feature 3).
**Build size:** one session.
**Non-scope:** no personalization, no clustering, no layout redesign, no per-category frequency.

### 2. Triage deck in /view

A "Review" button opens one card at a time: summary, action points, three big buttons plus skip, keyboard a/l/x/space, a visible "4 left" counter, and an end state that says done. Deck contents come from the same scorer as feature 1.
**Rationale:** the current infinite scroll of 144 cards is the anti-ADHD pattern; a finite deck with an exit is the pro-ADHD pattern. Also the single most demo-able artifact in the app: this is the screen a portfolio reviewer watches.
**Files:** server.py build_html (deck markup, JS state machine; /state endpoint already exists at server.py:1207).
**Model:** none.
**Acceptance:** deck loads at most 10 items; every card resolves to a state or an explicit skip; finishing shows a completion state; a full deck run takes under 2 minutes; works on iPhone PWA.
**Build size:** one session.
**Non-scope:** no swipe-gesture physics library, no animation framework, no separate route or SPA.

### 3. Auto-archive decay

Items untouched for a TTL auto-archive: News 7 days, everything else 21 days (constants at top of server.py). Runs in the existing retry_loop sweep. Reversible, and reported in the brief as "9 items aged out".
**Rationale:** kills the guilt pile mechanically instead of asking willpower to do it. The backlog can no longer grow without bound, which is the product promise (product-intent.md:20-22) enforced in code.
**Files:** server.py (sweep in retry_loop at :700, one constant block), daily_brief.py (aged-out line).
**Model:** none.
**Acceptance:** after one sweep on live data, every untouched item older than TTL carries state archive; active view shrinks accordingly; brief reports the count; unarchive works from the archive filter.
**Build size:** half a session. Pairs with feature 1 in one sitting.
**Non-scope:** no deletion, ever; no per-item custom TTLs; no ML "importance" exemptions.

### 4. Auth on mutating endpoints plus split binding (closes issue #2)

Require the bearer token on /delete, /state, /failures/delete, /ask (currently exempted by the is_ingest split at server.py:1159); serve reads on localhost/tailnet per the split-binding option 1 already scoped in STATE.md:33. Signed triage links from feature 1 are the auth path for email taps.
**Rationale:** an unauthenticated wipe-everything endpoint on 0.0.0.0 is indefensible in a public portfolio repo, and it is the only open issue on the whole GitHub account (STATE.md:33). Features 1-3 make state data valuable; this keeps it.
**Files:** server.py do_POST auth block, bind logic at :1252; client.py, extension/, brief links carry the token they already have.
**Model:** none.
**Acceptance:** unauthenticated POST to /delete and /state returns 401; iPhone shortcut, extension, menu bar client, and signed brief links all still work end to end; issue #2 closed with a commit reference.
**Build size:** one short session.
**Non-scope:** no HTTPS, no user accounts, no reverse proxy.

### 5. Repo truth pass

Delete app.py, app.py.backup, config.json.save, test_fix_verification.py (it asks for its own deletion). Add requirements.txt. Fix README: install section currently launches `python3 app.py` (README.md:89), the 420-line legacy pipeline with placeholder tokens and no junk gates; remove or implement the LM Studio claim (README.md:68); anchor BASE_DIR to `Path(__file__).parent` so server.py and daily_brief.py agree on where data lives.
**Rationale:** the WWDC 2027 frame means people who evaluate craft will read this repo. Today the documented entry point runs dead code and the README claims a runtime the code cannot speak to. Truth is a craft signal; a package manifest is the difference between "clone and run" and "guess my dependencies" (STATE.md:39 already flags it).
**Files:** app.py (delete), README.md, requirements.txt (new), server.py:17, daily_brief.py untouched.
**Model:** none.
**Acceptance:** fresh clone plus `pip install -r requirements.txt` plus the README commands yields a working server; no reference to app.py survives; README claims match code exactly.
**Build size:** one session.
**Non-scope:** no refactor of server.py, no test framework, no CI beyond existing gitleaks.

Explicitly deferred with reasons on record: native Swift client (fails one-session, revisit as the v1 flagship once the loop is proven), embedding-based scorer (cold start, drop-in later), personalization (blocked on state data existing at all).

---

## 8. WHAT IS WORKING (with evidence)

- **Capture, in production, daily.** 144 items; saves every month since June including 18 in August and one at 2026-08-17 05:14 (VERIFIED, live /view). Client LaunchAgent running on the M4 (VERIFIED, launchctl). Inbox-before-auth means rejected requests still leave a trace (server.py:1161-1165).
- **Extraction quality defense in depth.** Three junk gates with documented real-world kills: the 2026-07-31 outbreak was diagnosed, fixed, verified live 22/22, and purged (worklog.md:9-22, VERIFIED). Live failure list shows quality rejections still catching junk (VERIFIED).
- **Dedupe at content identity, not string identity.** Reddit /s/ aliases, redd.it, youtu.be, twitter/x collapse to canonical URLs (extractors.py:85-159, VERIFIED); the migration that merged live duplicates is logged (decision-log.md:65-68).
- **Deploy pipeline.** Push to main, M1 auto-deploys in 5 minutes with py_compile guard; verified working after the master-to-main rename (INFRA.md:105-110, VERIFIED doc; server responding today, VERIFIED live).
- **Repo hygiene at the git layer.** Clean tree, in sync with origin, single tidy branch, gitleaks CI green, full-history scan clean at 35 commits (INFRA.md:97-99), MIT licensed with Claude credited (README.md:202-204, LICENSE).

## 9. WHAT IS NOT WORKING (with evidence and root cause)

- **The product's reason to exist.** Zero act, zero archive, 2 revisit across 144 items and four months (VERIFIED, live /view). Root cause: no resurfacing mechanism exists anywhere in the code; daily_brief.py:47-65 hard-filters to the last 24 hours, so the backlog is structurally invisible. The v0.3 behavior ("prove people act") was declared in April, and v0.4 shipped seven features in July without touching it (roadmap.md:63-72): effort went where building was easy, not where the loop was broken.
- **Unauthenticated destructive endpoints on an open bind.** /delete, /state, /ask are exempt from auth (server.py:1159) while binding 0.0.0.0:7778 (server.py:1252). Anyone on the network can erase the knowledge base. Root cause: auth was designed for ingest only; the exemption list grew with each new endpoint. Known and open since 2026-07-30 (issue #2, STATE.md:33).
- **Documented entry point is dead code.** README.md:89 says `python3 app.py`; app.py is the pre-v0.4 pipeline: no extractors, no junk gates, a shipped placeholder auth token (app.py:33), unauthenticated /delete, its own 0.0.0.0 bind. Root cause: client.py superseded it in June and nobody retired the corpse.
- **README claims a runtime the code cannot use.** "LM Studio or Ollama" (README.md:68, :75, :82); the code speaks only the Ollama API (server.py:162, VERIFIED). Root cause: the v0.1 LM Studio setup (architecture.md:59-64) was swapped for M1 Ollama and the README kept the old claim.
- **Split-brain data paths.** server.py anchors to Path.home(), daily_brief.py to its own file location; ~/content-digest-app does not exist on the M4 (VERIFIED). A local dev run silently creates a second data universe. Root cause: repo moved during the 2026-07-30 consolidation, code anchor never updated.
- **No reproducible environment.** No requirements.txt or pyproject (VERIFIED); deps live in a README pip line plus tribal knowledge. Already flagged 2026-08-07 (STATE.md:39), still absent.
- **Stale docs posing as state.** todo.md still carries the v0.1 exit checklist unchecked from April; the parking lot lists a feature that shipped (mobile view); local data relics (June knowledge.json, June brief log) invite exactly the wrong conclusion about live usage. Root cause: doc discipline decayed after 07-19; the bridge handoff for this project was never created.
- **Cloud fallback contradicts the privacy posture.** Groq receives extracted page text whenever local inference is down (server.py:298-316, README.md:194 admits it). Mitigated by the empty-key opt-out, but the default shipped config on the M1 is UNVERIFIED either way.

## 10. Genuinely blocking open questions (max 3)

1. **Is the morning brief actually being delivered and opened?** INFRA.md:31 says the M1 owns the service; the only readable log stopped 2026-06-12 with "0 items" sends. Feature 1 rides on this channel; if delivery is dead, fix delivery first. One M1 command answers it: `tail ~/content-digest-app/daily_brief.log`.
2. **Does the M1 have RAM headroom to keep qwen2.5:3b plus nomic-embed-text resident while the retry sweep runs?** M1 spec is not recorded in INFRA.md and is unverifiable from this machine. Determines whether the scorer may use embeddings server-side or must stay pure arithmetic.
3. **Is Karl's per-version sign-off still operative?** roadmap.md:87 requires "Karl's review before the next begins", and worklog shows no Karl contact since 2026-04-07. If it is dead protocol, delete the rule; if live, v0.5 has an external dependency the plan must schedule.

---

Audit complete. Phase gate honored: no implementation, no repo mutation. Deliverable 2 is the bridge handoff written via `bridge.py handoff-write --project content-digest-app`.

---

## Addendum (2026-08-17, second pass): four gaps closed, phase gate still down

### A1. secrets.json, both machines (VERIFIED, values not echoed)

Local M4 copy (mtime 2026-08-12): `auth_token` was a well-known placeholder string, and `groq_api_key` held a live cloud API key. M1 copy (`~/content-digest-app/secrets.json`, read over SSH): identical shape, same placeholder token, same live key. No SMTP fields in either copy; the mail credential lives in config.json instead. (Both were replaced the same day: random token rolled, cloud key emptied.)

Consequence, and it upgrades the audit's security finding: **the production bearer token was a guessable placeholder.** client.py reads it from the M4 secrets.json and the M1 server accepts it, so ingest auth is decorative, not just the read/mutate endpoints. The constant-time compare shipped in 740aba8 is comparing against a placeholder.

**Feature 4 scope is amended to include:** generate a real random token; roll it to all four clients (iPhone Shortcut header, Chrome extension options, client.py via M4 secrets.json, and the signed brief links of feature 1); empty or rotate the Groq key as part of the same pass (it is live on two machines and unused whenever local inference is up); verify the M1 copy after the roll with a save round-trip.

### A2. Credential action: rotate the SMTP app password

config.json holds the SMTP app password in plaintext (VERIFIED), it is synced to the M1 by the nightly backup and lives in the M1's own runtime copy, and it has been echoed into terminal output, including during this audit run. Rotate it at the provider, update config.json on both machines, and confirm the next 07:00 brief sends. (Done by the owner the same day, verified with a live send.) This is an operator action, not a build feature; it goes ahead of feature 1.

### A3. docs/ and CLAUDE.md are untracked: this audit exists on one machine

`git ls-files` confirms 52 tracked files and none of them are docs/, CLAUDE.md, secrets.json, or config.json (.gitignore lines: `docs/`, `CLAUDE.md`, VERIFIED). This deliverable therefore lives only on the M4 (plus the nightly data backup to the M1; it is in no git history anywhere). **Feature 5 gains a decision point:** either commit docs/ (minus session-handoff internals) so the portfolio repo shows its product thinking in public, or keep docs/ private and accept that the repo's visible craft is code and README only. The April rationale for hiding docs ("internal development notes", worklog.md:76) predates the WWDC 2027 portfolio frame and should be re-decided, not inherited.

### A4. M1 verification results (all three commands run over SSH, read-only, VERIFIED)

1. **The brief delivers.** `tail ~/content-digest-app/daily_brief.log`: sends on 08-14 (3 items), 08-16 (1 item), and this morning 2026-08-17 07:00:03 (1 item) to the Gmail recipient. Open question 1 is resolved: the channel feature 1 rides on is alive and firing daily at 07:00 Dubai. Whether the emails get opened remains unmeasured, which is exactly what feature 1's tap-through will measure.
2. **secrets.json on the M1:** covered in A1. Open question about M1 config drift is moot once the token roll and password rotation in A1/A2 execute.
3. **RAM: the M1 has 8 GB and is at capacity.** `hw.memsize` 8589934592; PhysMem 7497M used, 137M unused, 1408M in compressor. Consequence, resolving open question 2: **the resurfacing scorer stays pure arithmetic on the M1.** Reading the existing embeddings.json cache is free; keeping models resident is not. qwen2.5:3b already pressures this box; adding scorer-time embedding calls risks pushing summarisation latency into the iPhone shortcut timeout. Any embedding-heavy work runs on the M4 at dev time or not at all.

### Remaining open question (was 3, now 1)

Only the Karl sign-off question survives: roadmap.md:87 requires per-version review, no Karl contact is evidenced since 2026-04-07, and whether v0.5 has an external reviewer dependency is a decision for the owner, not this audit.

Phase gate remains honored: no implementation, no repo mutation, no credential values reproduced in this document.
