# docs/worklog.md

## Worklog — Content Digest App

Append a dated note after every major session. Keep entries concise.

---

## 2026-07-31

**Session type:** Bug hunt + hardening (junk-item outbreak).

**What happened:**
- Diagnosed 7 junk items in the live KB ("Short Title Needed", "lnkd.in Redirect", "Agree & Join LinkedIn", "Learn More", "Untitled Article", 2 more): lnkd.in and linkedin.com fetches return HTTP 200 whose visible DOM is an authwall/interstitial; trafilatura extracted that boilerplate and the model summarized it. r.jina.ai also returns error bodies ("request timed out") with HTTP 200 that passed the old len>100 check. example.com and the server's own /view URL had no gate at all.
- extractors.py: new fetch_linkedin_content (JSON-LD SocialMediaPosting + og:description, authwall/signup-redirect detection, exclusive routing so the generic path never runs on LinkedIn). Short-link resolution in normalize_url (lnkd.in, bit.ly, t.co, and friends) so short links dedupe and store under the canonical target URL.
- server.py: three quality gates. (1) _blocked_url_reason: placeholder domains, localhost, private/CGNAT IPs. (2) _junk_content_reason: interstitial/authwall/proxy-error markers + minimum length/word-diversity, applied to all content paths including browser capture and the jina fallback. (3) _junk_analysis_reason: model can return {"unusable": true}; junk titles/summaries rejected post-analysis. New failure type "quality" (amber badge). Rejected pages become visible, retryable failures; never saved items.
- Verified live from residential IP: all 4 failing lnkd.in links now extract real post text; the ugcPost authwall fails clean; gates pass 22/22 unit checks with zero false positives on control articles.
- Purged the 7 junk items from the live KB via /delete (129 -> 122 items).

**Next session should start with:**
- Deploy to M1 (git pull + LaunchAgent restart; SSH from the MacBook is password-gated so it needs a manual run).
- Re-save the 4 lnkd.in links after deploy to confirm end-to-end.

**Session type:** Strategic brief + full v0.4 build.

**What happened:**
- Live research settled the Reddit question: API approval permanently unobtainable (Responsible Builder Policy, Nov 2025); .json endpoints dead (Dec 2025); old.reddit HTML verified working from residential IP; arctic-shift archive verified as fallback.
- Built extractors.py (Reddit, YouTube transcripts, X via fxtwitter, URL normalization). All extractors tested live against real URLs before integration.
- Integrated into server.py: extractor dispatch, browser-content passthrough, output validation, item states + /state, /ask with local embeddings + keyword fallback, auto-retry + inbox reconciliation.
- UI: state buttons and filter, ask box with cited answers. Daily brief: state pills, archived excluded.
- Rebuilt the Chrome extension in-repo (extension/) as a generic rendered-page capture layer.
- Found and fixed a silent production breakage: Groq fallback dead on two counts (decommissioned model, UA block).
- End-to-end test on isolated environment passed: Reddit save, passthrough save, state set, ask answered with sources.

**Same day, post-deploy hardening (all verified live on M1):**
- Deployed v0.4 to M1 over SSH: deps installed, nomic-embed-text pulled, 96 items backfilled with embeddings, LaunchAgent restarted.
- Fixed menu bar 401: client.py now reads auth token from secrets.json (placeholder had shipped in the sanitized file); client timeout 5s to 15s.
- Fixed timeouts: server moved to ThreadingHTTPServer; a slow /ask no longer blocks the iPhone shortcut or extension.
- Fixed duplicate saves: canonical URL identity per source (reddit /s/ and redd.it links resolved and collapsed to one thread URL, youtu.be to watch?v=, twitter.com to x.com, LinkedIn rcm/trk stripped). One-time migration merged the existing duplicate and pruned orphan embeddings.

**Next session should start with:**
- Verify morning brief renders state pills on a real send.
- Watch the first auto-retry sweep log on the M1.

---

## 2026-04-07

**Session type:** Planning and setup.

**What happened:**
- Karl reviewed the project over WhatsApp and a call. Full feedback synthesized.
- Key points: replace regex with trafilatura, fix delete persistence, adopt one-behavior-per-version discipline, set up repo-local markdown OS, use GitHub Desktop for pushes.
- Confirmed local repo linked to GitHub via GitHub Desktop.
- Created full markdown OS: CLAUDE.md and all docs/ files.

**Decisions made:**
- Replace regex with trafilatura (highest priority fix).
- Fix delete persistence before any new features.
- v0.1 exit criterion: Karl review and sign-off.
- GitHub Desktop for all commits, no CLI required.

---

## 2026-04-08

**Session type:** Code fixes and audit.

**What happened:**
- Ran Karl's full audit against app.py. Nine issues found, four classified must-have for v0.1.
- Fix 1: Replaced regex with trafilatura. Tested with real article URL. Summary quality confirmed cleaner.
- Fix 2: Added fetch failure guard. If trafilatura returns None, LLM is not called. User gets notification.
- Fix 3: Fixed persistent delete. Added /delete endpoint. JavaScript dismissItem now POSTs to localhost:7778/delete. CORS headers added. Tested and confirmed working.
- Fix 4: Added auth token. Requests to /add without correct Bearer token rejected with 401. iPhone shortcut updated and tested.
- All four fixes committed and pushed to master.
- docs/ added to .gitignore (internal development notes, not for public repo).
- README updated to reflect v0.1 fixes and setup instructions.

**Next session should start with:**
- Test 10 varied URLs across content types.
- Confirm deduplication is working.
- Signal Karl for v0.1 review.

---

## 2026-08-17

**Session type:** Security hardening + the resurfacing loop (kk2, post-audit build).

**What happened:**
- Feature 4 (commit 90c6614): auth on every POST endpoint, token-gated /view with a derived session cookie, trusted-source guard (loopback/RFC1918/Tailscale CGNAT only), placeholder tokens treated as unset. Credential roll: new random 64-hex auth_token on both machines, Groq key emptied on both. Issue #2 closed. 14/14 isolated auth checks plus live verification with a save round-trip.
- Micro-patch (df47d56): Locked page gained an in-page token form so installed PWAs (own cookie jar, no address bar) can unlock themselves.
- Features 1+3 in one sitting: daily brief resurfaces up to 3 backlog items (pure-arithmetic scorer: age x relevance, act first, category-diverse, 5-day cooldown) with HMAC-signed one-tap Act/Later/Archive links (72h expiry, GET /triage); decay sweep auto-archives untouched items past TTL (News 7d, default 21d) or after 3 ignored resurfacings, stamped auto_archived_at, reported in the brief. resurface.json tracks strikes; brief_last.html keeps the last render; --dry-run renders without sending or consuming strikes.
- server_base moved to config.json (runtime, never committed). Tailnet dependency of one-tap links documented in README.

**Next session should start with:**
- Feature 2 (triage deck in /view), then feature 5 (repo truth pass, publish docs/ minus session-handoff.md after redaction, delete the Karl sign-off rule from roadmap.md).

**Same day, feature 2 (triage deck):**
- /view gained a Review (N) button and a full-screen one-card-at-a-time deck: Act / Later / Archive / Skip buttons, keyboard a/l/x/space/esc, position counter, explicit completion state. Max 10 cards per deck.
- Same scorer as the brief: server.py imports pick_resurfaced from daily_brief.py (limit param added). One fatigue ledger (resurface.json): the brief's morning picks are on cooldown for the same-day deck, and deck skips stamp cooldown plus a strike so the next brief never repeats them.
- New POST /deck/skip (authed, excluded from inbox capture). Verified isolated: deck capped at 10, act first, cooldown/archived/fresh excluded, skip 401 unauth, skip updates ledger and disappears from both surfaces, brief still capped at 3.

**Same day, feature 5 (repo truth pass + docs publication):**
- Deleted app.py (legacy pre-v0.4 pipeline), app.py.backup, config.json.save, test_fix_verification.py. Added requirements.txt.
- server.py BASE_DIR now anchors to the file's own directory (was home-anchored; on the dev machine it silently pointed at a nonexistent path).
- README truth pass: install section now starts server.py/client.py (app.py was the documented entry point months after it died), LM Studio claim removed (code speaks Ollama only), v0.5 row added, v1 marked data-gated, Close the loop feature section added.
- roadmap.md: v0.5 delivered section, killed list from the red team audit recorded, sign-off rule retired (dead protocol, owner decision 2026-08-17).
- docs/ published to the public repo minus session-handoff.md, after a redaction pass (LAN and tailnet IPs, credential specifics, account identifiers).

## 2026-09-02: security pass from the fleet audit (kk1 Cowork)

Read-only audit report in the owner's fleet roadmap inbox; fixes verified against a scratch copy of the server on a spare port before pushing (unauthenticated `/add` returns 401 and its inbox row carries `authed: false`; a 1.1 MB body returns 413; a cookie-authenticated POST with a foreign `Origin` returns 403 while the same request with a bearer token passes; the `/view` script block no longer contains a raw `</script>` when an item title does; `_reconcile_inbox()` returns nothing for unauthenticated rows).

- Closed the pre-auth inbox reconcile path: `_record_inbox` stores whether the request was authenticated, the sweep re-queues only authenticated rows, and the inbox is capped at 500 entries. Unauthenticated LAN peers could previously have the server fetch, summarise and save any URL within six hours.
- Stored XSS in `/view`: inlined JSON escapes `</`, every `href` goes through `safeHref()` (http and https only, `rel="noopener"`).
- SSRF: `_blocked_url_reason` now rejects non-http schemes and empty hosts, checks IPv6 literals and `*.localhost`, resolves the hostname and rejects any address in loopback, private, link-local, reserved or CGNAT (tailnet) ranges, and re-checks the post-redirect URL after the direct fetch. Remote reads are capped at 2 MB (server and extractors), POST bodies at 1 MB.
- Cookie-authenticated POSTs must be same-origin (`Origin` or `Sec-Fetch-Site`); bearer requests are exempt because the token is a deliberate machine credential.
- `ai` failures are retried like `fetch` failures (an Ollama outage used to make every save in the window a permanent failure). `/delete` runs under `data_lock`; every `knowledge.html` write is atomic (tmp then rename).
- Extension 0.5.0: token moved from `chrome.storage.sync` to `chrome.storage.local` (re-enter it once in Options), and failed captures are queued locally and replayed every 15 minutes via `chrome.alarms`, so a capture made off the tailnet lands when the server is reachable again.
- `loopcheck-history.txt` added to .gitignore (it was untracked and unignored).
- Correction (see 2026-09-03): the 0.5.0 storage move shipped without a migration, so it neither preserved the settings nor actually removed the token from sync.
- Deferred to the fleet roadmap: runtime watchdog (heartbeat, brief health line, M4 observer), weekly act-rate rollup inside the brief, explicit loopback plus tailnet bind, `/view?token=` in the client, dead `OLLAMA_URL` setting, `TZ` constant.

## 2026-09-03: extension 0.5.1 — the migration 0.5.0 forgot

The 0.5.0 storage pass (2026-09-02) flipped every `chrome.storage.sync` call to `chrome.storage.local` and shipped **no migration**, which caused two things:

- **Silent config loss.** On upgrade `storage.local` was empty, so both the options page and the service worker fell back to the hardcoded `DEFAULTS` — server `http://localhost:7778`, empty token. Nothing prompted, nothing errored at save time; captures just started failing against a server that was not there.
- **The token never actually left sync.** The old 64-char bearer token stayed in `chrome.storage.sync` and kept replicating to the Google account. Moving the *read* to local without purging the old *write* location closed nothing: the exposure the security pass was written to fix survived it intact.

Fix, in `background.js` `chrome.runtime.onInstalled`:

- One-time migration guarded by `migratedFromSync` in `storage.local`, so it never runs twice and never re-fills a key the user has since typed in.
- Migrates every key the options page manages (`server` and `token`, not just the token), writing each only when `storage.local` has no non-empty value for it. Local always wins.
- Calls `chrome.storage.sync.clear()` unconditionally once the copy is written, including when there was nothing to recover — leaving the token there is the bug.
- Wrapped in try/catch at every step: an unreadable or empty sync store still sets the guard and still attempts the clear, and the listener never throws. One console line per path taken.

Manifest bumped to 0.5.1. The options-page comment no longer tells the user to re-enter the token by hand, and the README upgrade note matches. Verified by `node --check` on both JS files, `json.tool` on the manifest, and a walkthrough of fresh install / upgrade-with-sync-token / upgrade-where-a-token-was-already-typed.

## 2026-09-03: extension 0.6 capture rewrite, paste-first popup

- Replaced automatic toolbar submission with a popup. The URL field opens
  empty; the user pastes the exact URL and clicks Send to Content Digest. The
  popup shows a working state, then the honest outcome (saved, already saved,
  queued, refused, failed), plus Save current page, Open Content Digest,
  Settings, a collapsed recent-activity list, and the retry queue count.
  Manual paste is the primary workflow; page and right-click capture are
  optional conveniences.
- Added right-click target capture in `content.js`. LinkedIn posts resolve from
  a post permalink or `urn:li:activity` ancestor when present. Because the
  current LinkedIn markup exposed neither for real posts, a narrow main-world
  bridge (`bridge.js`, LinkedIn only) observes LinkedIn's own Copy link to post
  action during an explicit post resolution. Feed containers are refused when
  no item identity can be proven.
- Added extension-side wrapper decoding (LinkedIn safety/go, Google, Facebook,
  Reddit, href.li, away.vk.com). A safety wrapper that yields a bare
  `lnkd.in/<code>` uses the containing post identity or is refused. Post-shaped
  `lnkd.in/p/<code>` links are resolved in the extension to the direct
  `linkedin.com` permalink before POSTing.
- Moved extension submissions to `/add_sync`, with distinct saved, duplicate,
  failed, invalid, configuration, and queued feedback. Authentication and
  network failures now enter the existing 15-minute queue instead of vanishing.
- Fresh installs no longer materialize a fake localhost setting. Existing
  local values and the guarded sync purge are preserved; manifest bumped to
  0.6.0 so the update event runs. Options gained Test connection (`GET
  /health`, then authenticated `GET /failures`).
- Automated: `node tests/extension_acceptance.test.js` passed 46 assertions at
  handoff, then 62 after fixtures were added for the two refusal paths that
  correspond to the real feed right-click and safety-wrapper captures, plus
  static guards on the bridge (LinkedIn only, MAIN world, no logging, storage,
  or network) and the content script (single scoped listener, removed on
  finish). All extension JS files passed `node --check`; the manifest passed
  `python3 -m json.tool`; `git diff --check` passed; `server.py`,
  `extractors.py`, `client.py`, `daily_brief.py`, `.gitleaks.toml`, and the
  gitleaks workflow are unchanged.
- Live on the M4 (Chrome, unpacked): version 0.6.0 was reloaded. The popup was
  visually verified: empty URL field, Send to Content Digest, Save current
  page, Open Content Digest, Settings, Ready status, and the existing retry
  queue count. A real LinkedIn short post URL pasted into the popup showed the
  working state, was resolved, reached the server as the direct linkedin.com
  post URL with valid authentication, and the server honestly reported that it
  already existed (the same post was already saved). Earlier in the day a
  toolbar capture of the LinkedIn feed itself was refused, and after the
  resolver correction a right-click on a real post used LinkedIn's own Copy
  link to post action and reached the server through the normal authenticated
  path. Open Content Digest was not clicked in the final run because it
  performs the one-time authenticated view handoff.
- Not tested live (owner approval needed, destructive or state-changing):
  wrong or removed token, changed server address, clean-profile
  uninstall/reinstall migration, deleting the historical `/feed/` item. These
  paths have automated coverage only. The historical `/feed/` knowledge item
  and the roughly three queued captures in extension storage were left intact.
- No commit and no push had occurred at handoff.

## 2026-09-05: D6 weekly loop check, the measurement instrument (kk2 Cowork)

Measurement phase, no product change. Live counts at start: 179 items, act 0,
revisit 2, archive 147 (all by decay), 30 untouched; the server logged no
requests and `set_item_state` recorded neither when nor from where a state
changed, so the 09-17 read could not tell an email tap from a deck action.

- `server.py`: `set_item_state(url, state, source)` stamps `state_changed_at`
  and `state_source` on the item and appends one JSON line (at, url, from, to,
  source) to `triage_log.jsonl`. Sources: `triage-link` (brief), `deck`,
  `view` (knowledge base page), `api` (anything else), `decay` (auto-archive).
  Deck skips log as `to: skip`. The page and deck send their source in the
  `/state` body; it is allowlisted and only ever used for the log.
- `daily_brief.py`: `weekly_rollup`, `format_loopcheck_row`,
  `format_loop_line`, `append_loopcheck_row` (pure functions), plus
  `--weekly [--dry-run]`. The Monday brief carries a "Loop this week" line and
  appends a dated row to `loopcheck-history.txt` (once per date). Exclusion
  windows and the 2026-08-17 baseline are constants; clean days are subtracted
  in both the week and the since-baseline figures.
- `tests/test_daily_brief_rollup.py`: 11 unit tests, stdlib only. A temp-dir
  server run proved the three sources and the row end to end before commit.
- `.gitignore`: `triage_log.jsonl` (runtime data). No new runtime `.py`, so the
  host deploy list is unchanged.
- Retires the external weekly SSH loop-check task once the first row is
  written on the host; that task failed exactly when the host was offline.

## 2026-09-05: D1 runtime watchdog (kk2 Cowork)

Second measurement instrument. The two capture outages in August were found
by the user, days late, because nothing watched the path. Now:

- `server.py`: `heartbeat.json` every 5 minutes (at, started_at, version, pid);
  `clients.json` stamps the last authenticated contact per `X-Client`
  (`mac-client`, `extension`, `shortcut`, `view`, `triage-link`, `brief`, else
  `api`); a valid signed triage tap counts as contact, `/health` polls and
  unauthenticated requests never do. `/health` now carries version,
  started_at, last_save_at, last_client_contact_at, clients and the failure
  count. A content-free request log (`[req] METHOD path status client=`) skips
  `/health` and `/assets/`; the query string is dropped so `/triage` URLs stay
  out of the log. `SERVER_VERSION` replaces the stale v0.4 banner.
- `daily_brief.py`: "Host health" line when the last save or the last client
  contact is 48 h or older (or has never happened); on a day with no client
  contact in 24 h, `save_resurface(..., strike=False)` stamps the cooldown
  without a strike (C10), so an outage cannot push items into auto-archive.
- `client.py`: polls `/health` every 15 minutes with no credentials, shows the
  result in a greyed menu row, posts one banner after two consecutive misses
  and puts `!` beside the icon, posts one recovery banner. `CD_HEALTH_URL` and
  `CD_HEALTH_POLL_SECONDS` exist for Terminal tests only. Live test against a
  closed port then a fake server: miss 1, miss 2, alert, miss 3, recovered.
  Quirk met on the way: the LaunchAgent's PYTHONHOME poisons any child Python
  (the test harness had to `env -u` it; the client itself spawns none).
- Extension 0.6.1: `X-Client: extension` on `/add_sync` and the options Test
  connection; acceptance suite 64 assertions.
- Tests: 18 unit tests in `tests/test_daily_brief_rollup.py`.
- `.gitignore`: `heartbeat.json`, `clients.json`. No new runtime `.py`.
- README: Shortcut recipe gains the header and a Show Result step; deploy
  interval corrected to the measured 15 minutes (plist changed 2026-08-18,
  every doc still said 5).

## 2026-09-05: small debts from the fleet audit, one commit (kk2 Cowork)

Behaviour-neutral for the loop; nothing the measurement can see.

- `client.py`: View Knowledge Base opens plain `/view` (audit A5). The token no
  longer lands in browser history on every click; a browser that has not been
  unlocked gets the Locked page and asks once.
- `server.py`: one `TZ` constant replaces 13 inline `timezone(timedelta(hours=4))`
  constructions (audit B9). `retry_loop` sweeps 10 minutes after start and then
  every 6 hours; the first sleep used to be 6 hours, and because every deploy
  restarts the server, a day with three deploys (2026-09-04) never swept once.
  The sweep now logs one line every time it runs, even when nothing is queued.
- README: `local_settings.py` is client-only (an `OLLAMA_URL` there is dead,
  audit B2); `config.json` keys named, the brief time belongs to the LaunchAgent
  (the unread `send_hour_dubai` and `send_minute_dubai` keys, audit B3, stay in
  the host's file until the owner removes them; not edited on the host).
