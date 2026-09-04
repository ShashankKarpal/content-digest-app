# Chrome Extension Audit and Rewrite Brief

Written 2026-09-03. Audience: an autonomous coding agent with this repository on
disk and no conversation history. Everything you need is in this file or cited
from a file in this repo, a command with its output, or a commit hash.

The owner is Shashank Karpal, called Shanky. He is the only user of this
product. He wrote the docs in `docs/`. He is not a full-time developer; explain
changes in plain language and give exact runnable commands.

---

## 0. Constraints for you, the rewriting agent

Read these before touching anything.

1. **Do not print, log, echo, paste into a file, or commit the contents of
   `secrets.json`.** It is gitignored (`.gitignore` line 1, `secrets.*`) and
   holds a 64-character bearer token plus SMTP credentials. Reference it by
   shell substitution only, as shown in section 10. The tracked template is
   `secrets.example.json`, which contains placeholders only.
2. **Do not push.** Do not `git commit`, `git push`, `git checkout`, `git reset`,
   or `git stash` without Shanky saying so in the current session. This repo is
   public at `github.com/ShashankKarpal/content-digest-app`, and pushing to
   `main` triggers a live deploy (see section 7.6).
3. **Do not remove or weaken `.gitleaks.toml` or
   `.github/workflows/gitleaks.yml`.** The workflow runs on push, pull request,
   dispatch, and a weekly cron. The allowlist in `.gitleaks.toml` covers exactly
   two brand-provenance files and nothing else.
4. **Do not put a LAN address, a tailnet address, or a credential into any
   tracked file.** `README.md` line 117 states this rule. `docs/` is published
   to the public repo. This brief follows the rule; keep following it. The real
   server address lives in the gitignored `local_settings.py` (read by
   `client.py` lines 12-15) and in the gitignored `config.json`.
5. **Match the existing style.** Plain Manifest V3 JavaScript, one file per
   concern, no build step, no bundler, no framework, no TypeScript, no npm
   dependency. The current extension is four text files totalling under 10 KB.
   Keep it that way.
6. **Verify, do not assert.** Every claim you make in your report must be backed
   by a command you ran and its output, a file path with a line number, or a
   commit hash. Section 10 gives you the verification commands. If you cannot
   run a check, say so and label the statement inference.
7. **Prose style Shanky requires:** no em dashes, no curly quotes, no emoji.
   Commas, periods, colons, semicolons, parentheses.

---

## 1. What this product is, and what you are allowed to change

`CLAUDE.md` at the repo root is the binding instruction file. Quoting it
directly:

Line 20: "A tool that solves saved-content hoarding. Not a link saver. Not a
read-later app."

Line 24, the core loop: "**capture -> summarize -> resurface -> review -> act or
archive**"

Lines 28-30, the three tests every change is judged against:

> - **Capture:** Is saving faster, more reliable, and more frictionless?
> - **Return and review:** Is the user coming back to their saved content?
> - **Action and archive:** Is the user doing something because of what they saved?

Lines 38-40, the version boundary that governs this work:

> ### v0.1 - Prove people save
> Goal: frictionless capture and trustworthy summaries.
> Do not expand scope unless it directly improves capture reliability or summary quality.

**The rewrite is a capture-reliability project and nothing else.** Judge every
proposed change against the first bullet only. If a change does not make saving
faster or more reliable, it is out of bounds for this task, including anything
belonging to v0.2 (digest, item states, review flow; `CLAUDE.md` lines 42-44),
v0.3 (grouping, ranking, clutter suppression; lines 46-48), or v1
(personalization; lines 50-52).

Three further hard constraints:

- `docs/roadmap.md`, "Killed (red team audit 2026-08-17; do not resurrect
  without new evidence)" lists "LinkedIn saved-posts bulk harvesting: more input
  into the loop's narrow end." **Do not build bulk harvesting.** A per-item
  capture that works is in scope; a scraper that drains his LinkedIn saved list
  is not.
- `CLAUDE.md` lines 58-63: prefer the smallest change that proves the next user
  behavior, work in tiny steps, do not add speculative abstractions, preserve
  existing working behavior, and label every task must-have, nice-to-have, or
  later.
- `CLAUDE.md` lines 70-73: at the end of the session, update
  `docs/session-handoff.md`, `docs/decision-log.md`, `docs/architecture.md` if
  the system shape changed, and append a dated note to `docs/worklog.md`. Note
  that `docs/session-handoff.md` and `CLAUDE.md` are gitignored (`.gitignore`,
  the lines under "internal working notes stay local"); they are local files,
  not published ones.

### 1.1 The measurement window

Section 2 of the task that produced this brief states that a measurement window
closes around 2026-09-17.

**I could not find that date anywhere in the repository.** I searched `docs/`
and `README.md` for `09-17`, `measurement`, `window`, `deadline`, and
`checkpoint`; the only hits were unrelated lines in
`docs/redteam-audit-2026-08-17.md` about a 14-day dormancy threshold.
`docs/current-phase.md` carries no date after its header (`## Current Version:
v0.4 (shipped in code 2026-07-19; deploy to M1 pending)`), and its exit criteria
at line 9 are behavioral, not dated:

> Exit criteria for this phase: user sets a state on at least one item per
> digest cycle, and asks the knowledge base at least once a week without being
> prompted.

Treat 2026-09-17 as an owner-stated constraint from the 2026-09-03 session, not
a repo fact. **What it implies for you:** you have roughly two weeks of real
usage to produce signal, so ship a capture path Shanky will actually use every
day within this session, and do not spend the window on refactoring. A rewrite
that lands on 2026-09-16 produces zero data. Prefer working capture on
2026-09-03 over an elegant capture on 2026-09-15.

---

## 2. The failure that triggered this brief

Three real captures on 2026-09-03, all authenticated, all reaching the server,
all useless. Verified against the live server inbox
(`ssh m1`, `~/content-digest-app/inbox.json`):

```
2026-09-03T08:49:18.920669+04:00  authed=True  https://www.linkedin.com/feed/
2026-09-03T08:50:42.118367+04:00  authed=True  https://www.linkedin.com/feed/
2026-09-03T08:51:59.430332+04:00  authed=True  https://www.linkedin.com/safety/go/?url=https%3A%2F%2Flnkd.in%2Fey84cgC7&urlhash=wRZf&mt=ADcNCm-NmSQ8BsqRBjnfwTWJ-2e317j
```

- 08:49:18 was a toolbar icon click. It ran `capture(tab)`
  (`extension/background.js` line 106), which sends `location.href`
  (`extension/background.js` line 71) plus the feed's rendered text.
- 08:50:42 was a right-click on something that looked like a link but was not an
  anchor element, so `info.linkUrl` was undefined
  (`extension/background.js` line 173) and the handler fell through to
  `capture(tab)` at line 183. Same result.
- 08:51:59 was a right-click on a real anchor, so `info.linkUrl` was LinkedIn's
  outbound redirector wrapper, posted verbatim with no page content
  (`extension/background.js` line 175).

### 2.1 What each one became

**Capture 1 was saved as a real-looking item under a URL that is not a
document.** From `knowledge.json` on the server:

```
2026-09-03T08:49:32.815198+04:00 | https://www.linkedin.com/feed/
   title: Headroom AI Fix for Wasted Tokens
   cat: Work | rel: 4
```

The summary describes whatever post happened to sit at the top of his feed at
08:49. The stored identity is `https://www.linkedin.com/feed/`, which is not a
stable document. Tomorrow it is a different post.

**Capture 2 was silently discarded.** `process_url` deduplicates on URL
(`server.py` lines 675-678):

```python
if url in [i["url"] for i in data["items"]]:
    print(f"[skip] Already saved: {url[:60]}")
    _remove_failure(url)
    return {"status": "already_saved", "url": url}
```

`https://www.linkedin.com/feed/` was already an item from 08:49:32, so the
08:50:42 capture returned `already_saved` and vanished. It is in
`inbox.json`, it is not in `knowledge.json`, and it is not in `failures.json`.
The extension showed a green tick, because `postAdd` only checks `resp.ok`
(`extension/background.js` line 31) and the server answers 200 before it even
starts processing (`server.py` lines 1602-1605, 1668). **The user was told the
save succeeded when nothing was saved.** This is the worst bug in the current
design: a bad URL identity turns every subsequent feed capture into a silent
no-op for the life of the item.

**Capture 3 became a visible fetch failure.** From `failures.json`:

```
https://www.linkedin.com/safety/go/?url=https%3A%2F%2Flnkd.in%2Fey84cgC7&urlhash...
   error_type: fetch   reason: Could not fetch URL content
```

The wrapper was stored as the item identity because nothing unwraps it.
`normalize_url` (`extractors.py` lines 87-146) resolves short links only for
hosts in `_SHORTENER_HOSTS` (`extractors.py` lines 33-36), and
`linkedin.com` is not one. The wrapper's `url`, `urlhash`, and `mt` query
parameters are not in `_DOMAIN_TRACKING["linkedin.com"]` (`extractors.py` line
64), so they survive normalization too.

### 2.2 A second-order finding you must not miss

Unwrapping `safety/go` is necessary but **not sufficient**. Verified with a
read-only network test from the M4 on 2026-09-03:

```
step 1 unwrap -> https://lnkd.in/ey84cgC7
step 2 resolve -> https://lnkd.in/ey84cgC7     status 200
```

`lnkd.in/<code>`, the form LinkedIn uses for outbound links inside post bodies,
answers HTTP 200 with a 5,183-byte non-redirecting interstitial. There is no
`Location` header, no `meta refresh`, and no `window.location` assignment in the
body. `_resolve_short_link` (`extractors.py` lines 71-84) relies entirely on
`r.geturl()`, so it returns the short link unchanged, and the pipeline then
kills it at the junk gate or the LinkedIn extractor.

By contrast, `lnkd.in/p/<code>`, the form LinkedIn's mobile share sheet
produces, redirects correctly:

```
https://lnkd.in/p/evwG7VAv
  geturl -> https://www.linkedin.com/posts/hamna-aslam-kahn_someone-just-open-sourced-...
  len    -> 182524
```

**That single difference explains why the iPhone Shortcut works and the desktop
extension does not.** Fifty-one of the 265 inbox rows are `lnkd.in/p/` links and
they summarize cleanly; the one `lnkd.in/<code>` derived link failed.

### 2.3 The shape that is proven to work

Eleven inbox rows are `linkedin.com/feed/update/urn:li:activity:<id>` URLs, and
they became good items. Examples from `knowledge.json`:

```
2026-08-28T09:53:16 | .../feed/update/urn:li:activity:7498695844070723585?... | 9 Claude Skills for Prompt Optimization
2026-08-28T09:53:03 | .../feed/update/urn:li:activity:7498716445107998720?... | Claude Code Prompt for Engineers
```

143 rows are `linkedin.com/posts/<slug>` permalinks, which also work. So for
LinkedIn the target URL shapes are known and proven: `linkedin.com/posts/...`
and `linkedin.com/feed/update/urn:li:activity:<id>`. The rewrite's job on
LinkedIn is to produce one of those two, not to invent a new path.

---

## 3. Complete file inventory: `extension/`

Six files, 11,570 bytes total. Sizes from `ls -la extension/` on 2026-09-03.

### 3.1 `extension/manifest.json` (629 bytes, 20 lines)

Manifest V3. Version `0.5.1` (line 4). Permissions (line 6): `activeTab`,
`scripting`, `storage`, `contextMenus`, `alarms`. Host permissions (line 7):
`http://*/*` and `https://*/*`. The `action` block (lines 8-10) has a
`default_title` and **no `default_popup`**, which is why clicking the toolbar
icon fires `chrome.action.onClicked` instead of opening a UI. Background is a
service worker at `background.js` (lines 11-13). `options_page` is
`options.html` (line 14). No `commands` block, so there is no keyboard shortcut.

### 3.2 `extension/background.js` (6,650 bytes, 184 lines)

The whole extension. Function by function:

| Lines | Name | What it does |
|---|---|---|
| 6-9 | `DEFAULTS` | `{ server: "http://localhost:7778", token: "" }`. The `localhost` default is load-bearing in the 0.5.0 incident; see section 9.6. |
| 11-16 | `getSettings()` | `chrome.storage.local.get(DEFAULTS, resolve)`. Local, never sync. |
| 21-22 | `PENDING_KEY`, `FLUSH_ALARM` | `"pending"` and `"cd-flush"`. |
| 24-33 | `postAdd(payload)` | POSTs JSON to `{server}/add` with `Authorization: Bearer <token>`. Throws `HTTP <status>` if `!resp.ok`. Trailing slash on the server URL is stripped. |
| 35-40 | `queuePending(payload)` | Appends `{...payload, queuedAt}` to `storage.local.pending`, keeps the last 100, creates the 15-minute alarm. |
| 42-51 | `flushPending()` | Replays every queued payload; keeps the ones that still throw; clears the alarm when the queue empties. |
| 53-55 | `chrome.alarms.onAlarm` | Calls `flushPending()` when the alarm fires. |
| 57-74 | `grabPageContent()` | Injected into the page. Uses `window.getSelection()` if the trimmed selection is longer than 80 characters, otherwise `article`, then `main`, then `body` `innerText`. Collapses 3+ newlines, slices to 20,000 characters. Returns `{ url: location.href, title: document.title, content }`. **`location.href` is the bug in section 2.** |
| 76-80 | `setBadge(tabId, text, color)` | Sets the badge and clears it after 4,000 ms. This is the only feedback the extension gives. |
| 82-104 | `capture(tab)` | Guards on `tab.id` and `^https?:`; silently returns otherwise. Runs `grabPageContent` via `chrome.scripting.executeScript`, sets an amber `...` badge, calls `postAdd`, sets a green tick on success. On `HTTP 401` or `HTTP 403` it sets a red `401` badge and **returns without queueing, discarding the payload** (line 96). On any other failure it queues and sets an amber `Q`. On an exception it sets a red cross. |
| 106 | `chrome.action.onClicked` | Bound directly to `capture`. |
| 112-113 | `MIGRATION_KEY`, `MIGRATED_KEYS` | `"migratedFromSync"` and `Object.keys(DEFAULTS)`, so `server` and `token`. |
| 115-159 | `migrateFromSync()` | The 0.5.1 fix. Guarded by `migratedFromSync` in local. Reads `server` and `token` from sync, copies each into local **only when local has no non-empty string** (line 134, "local always wins"), then calls `chrome.storage.sync.clear()` unconditionally, then sets the guard. Every step in try/catch; one console line per path. |
| 161-168 | `chrome.runtime.onInstalled` | Creates one context menu item, id `cd-save`, title "Save to Content Digest", contexts `["page", "selection", "link"]`. Calls `migrateFromSync()` when the reason is `install` or `update`. |
| 170-184 | `chrome.contextMenus.onClicked` | If `info.linkUrl` is set, POSTs `{ url: info.linkUrl }` with **no title and no content**, so the server must fetch it; queues on failure. Otherwise falls through to `capture(tab)`. |

### 3.3 `extension/options.js` (852 bytes, 23 lines)

Reads `server` and `token` from `chrome.storage.local` with `DEFAULTS` (line 6),
fills two inputs, and on the Save click writes both trimmed values back to
`chrome.storage.local` (lines 11-23), showing "Saved." for 2 seconds.

### 3.4 `extension/options.html` (1,544 bytes, 28 lines)

Two labelled inputs (`server` text, `token` password), a Save button, a status
span, and an inline dark stylesheet. The accent `#b17e51` is the Ink and Bone
copper, set in commit `a8c71ff`. No validation, no connection test.

### 3.5 Icons

`icon16.png` (300 bytes), `icon48.png` (834 bytes), `icon128.png` (2,305 bytes).
Referenced from `manifest.json` lines 15-19. Regenerated in commit `5905386`.
There is no reason to touch these.

### 3.6 Defects visible from the code alone

- **D1. Wrong URL identity on any feed page.** `background.js` line 71 sends
  `location.href` unconditionally. Section 2 has the evidence.
- **D2. Success reported for a discarded save.** `postAdd` treats the server's
  immediate 200 as success (`background.js` line 31; `server.py` lines 1602-1605
  and 1668). The server dispatches processing on a background thread
  (`server.py` line 1670) and never tells the caller the outcome. The
  synchronous endpoint that does report an outcome, `/add_sync` (`server.py`
  lines 1656-1665), is not used by the extension.
- **D3. Payload discarded on 401 or 403.** `background.js` line 96 returns
  before `queuePending`. A misconfigured token therefore loses the capture
  permanently, and the only signal is a badge that disappears in 4 seconds.
- **D4. No popup, no URL field.** `manifest.json` lines 8-10 declare no
  `default_popup`. There is no way to paste a copied permalink.
- **D5. The selection context does not do what it appears to do.** Registering
  `"selection"` (`background.js` line 165) adds a menu entry, but the handler
  has no selection branch. It falls to `capture(tab)`, and `grabPageContent`
  re-reads `window.getSelection()` in the page, so a selection longer than 80
  characters does become the content. **The URL is still `location.href`.** So a
  selection save on a LinkedIn feed stores the right text under the wrong
  identity, and then collides with every other feed save. This is a correction
  to the loose description "the selection context does nothing distinct": it
  does something, undocumented, and the something is still wrong. Inference from
  code reading; confirm by capturing a selection and checking `inbox.json`.
- **D6. No redirector unwrapping anywhere.** Neither the extension nor
  `normalize_url` handles `linkedin.com/safety/go/?url=`. See section 2.1.
- **D7. Duplicate context menu creation on update.** `chrome.contextMenus.create`
  runs on `onInstalled` for both `install` and `update` (`background.js` lines
  161-166) without `chrome.contextMenus.removeAll()` first, so a version bump
  raises "Cannot create item with duplicate id cd-save" in the service worker
  log. The menu still works because Chrome persists it. Inference from the MV3
  API contract; verify by bumping the version, reloading, and reading the
  service worker console.
- **D8. Silent no-op on non-http tabs.** `background.js` line 83 returns with no
  badge and no message on a `chrome://`, `file://`, or PDF viewer tab.
- **D9. Broad host permissions.** `http://*/*` and `https://*/*`
  (`manifest.json` line 7). Justified today by `chrome.scripting.executeScript`
  running anywhere, but worth narrowing if the rewrite moves to
  `activeTab`-triggered injection only.

---

## 4. The server surface the extension touches

`server.py` is 1,687 lines. Only these parts matter to you. Do not change server
behavior unless a capture requirement forces it, and say so explicitly if it
does.

| Lines | What |
|---|---|
| 29 | `INBOX_FILE = BASE_DIR / "inbox.json"`. Gitignored (`.gitignore` line 2). The durable capture log. |
| 122-123 | `MAX_FETCH_BYTES = 2_000_000` and `MAX_BODY_BYTES = 1_000_000`. The POST cap is the extension's ceiling; the comment notes captures are 20k characters or less. |
| 140-147 | `_address_is_internal(addr)`: private, loopback, link-local, reserved, multicast, unspecified, and `100.64.0.0/10`. |
| 150-185 | `_blocked_url_reason(url, resolve=True)`: the SSRF gate added 2026-09-02. Rejects non-http schemes, empty hosts, placeholder domains, `.local`, `.localhost`, IP literals, and any hostname that resolves to an internal address. Re-called on the post-redirect URL. |
| 188-207 | `_junk_content_reason(text)`: rejects empty content, under 200 characters, under 40 words, under 20 distinct words, and interstitial markers when the body is under 2,500 characters. Applies to browser-captured content too (`server.py` lines 682-685). |
| 210-224 | `_junk_analysis_reason(analysis)`: final gate on model output. |
| 231-241 | `AUTH_TOKEN` loaded from `secrets.json`; known placeholders are treated as no token, and the server then rejects everything. |
| 246-249 | `_session_cookie_value()`: HMAC of the token, used for the `/view` cookie so the raw token never lands in browser storage. |
| 255-263 | `_trusted_source(ip)`: loopback, RFC1918, and CGNAT only. Enforced before auth on both GET (line 1427) and POST (line 1562). |
| 601-617 | `_record_inbox(url, authed=False)`: writes `{url, received_at, authed}` to the front of `inbox.json`, capped at 500 entries, atomic tmp-then-rename. **These three field names are the contract your tests read.** |
| 662-750 | `process_url(url, content=None)`: normalize, SSRF gate, dedupe (675-678), use browser content trimmed to 3,000 characters if it passes the junk gate else refetch (679-696), junk gate, analyze, model-output gate, validate, save under `data_lock`, rewrite HTML atomically, embed. |
| 856-879 | `_reconcile_inbox()`: re-queues inbox URLs older than 30 minutes that never became items or failures, **skipping any row without `authed`** (line 867). Max 10 per sweep. |
| 882-901 | `retry_loop()`: every 6 hours, retries `fetch` and `ai` failures up to 3 times and re-queues reconciled orphans. |
| 1391-1394 | `_bearer_ok()`: `hmac.compare_digest(auth.encode(), f"Bearer {AUTH_TOKEN}".encode())`. Constant-time. This is the extension's auth path. |
| 1396-1404 | `_cookie_ok()`: constant-time compare against `_session_cookie_value()`. The `/view` path only. |
| 1409-1418 | `_same_origin()`: checks `Sec-Fetch-Site` and `Origin` against `Host`. |
| 1554-1559 | `do_OPTIONS`: CORS preflight, allows `Content-Type` and `Authorization`. |
| 1561-1670 | `do_POST`. In order: trusted-source guard (1562), body size cap and 413 (1571-1573), body parse, `authed = self._authed()` (1578), inbox record **before auth** for ingest paths (1583-1586), auth gate returning 401 (1592-1594), same-origin refusal for cookie-auth POSTs returning 403 while bearer requests are exempt (1598-1600), then `200 OK` (1602-1605) and the endpoint switch. |
| 1656-1665 | `/add_sync`: validates the scheme, calls `process_url` **synchronously**, and returns the real result: `saved`, `already_saved`, `failed` with `error_type` and `reason`, or `invalid`. |
| 1667-1670 | **There is no explicit `/add` route.** Any POST path not matched above falls through here, answers `{"ok": true}` immediately, and starts `process_url` on a daemon thread. `/add` works by accident of the fallthrough, and so would `/anything`. If you want the extension to know whether a save succeeded, `/add_sync` is the endpoint; it already exists and needs no server change. |

Relevant `extractors.py` lines:

| Lines | What |
|---|---|
| 33-36 | `_SHORTENER_HOSTS`: `lnkd.in`, `bit.ly`, `t.co`, `tinyurl.com`, `buff.ly`, `ow.ly`, `goo.gl`, `rebrand.ly`, `cutt.ly`, `t.ly`, `shorturl.at`, `rb.gy`. |
| 39-47 | `_get()`: 2 MB read cap. |
| 54-65 | `_GLOBAL_TRACKING` and `_DOMAIN_TRACKING`. LinkedIn strips `rcm`, `trk`, `originalSubdomain`, `midToken`, `midSig`, `trkEmail`. It does **not** strip or unwrap `url`, `urlhash`, `mt`, `lipi`, or `isSdui`. |
| 71-84 | `_resolve_short_link()`: one `urlopen`, returns `r.geturl()`, cached, returns the input on failure. Fails on `lnkd.in/<code>` for the reason in section 2.2. |
| 87-146 | `normalize_url()`: shortener resolution, tracking-param strip, then per-site canonical identity for Reddit, YouTube, X, and LinkedIn. |
| 400-450 | `fetch_linkedin_content()`: JSON-LD `SocialMediaPosting` first, `og:description` fallback, authwall and signup-redirect detection. Exclusive routing; the generic trafilatura path never runs on LinkedIn. |

---

## 5. What the other docs say that constrains you

| File | What it constrains |
|---|---|
| `CLAUDE.md` (root, gitignored) | The core loop, the version boundaries, the development principles, the operating rules, and the required response format for substantial tasks. Section 1 above quotes the binding lines. |
| `docs/product-intent.md` | Line 13: "Save anything in under five seconds." Line 23: "Success is not a bigger database of saved links. Success is the user doing something because of what they saved." Lines 50-55 rule out being a read-later app, a note app, a social bookmarker, or a research aggregator. |
| `docs/current-phase.md` | Header says v0.4 in code. Line 7 says the behavior under test is "people return and act". Lines 23-33 are the historical v0.1 scope. Lines 36-44 list what was out of scope for v0.1, including "LinkedIn saved posts harvesting (future, not assigned to a version yet)". |
| `docs/session-handoff.md` (gitignored) | Last updated 2026-07-19, badly stale; it still lists the v0.4 M1 deploy as pending, which happened. Line 34 records the durable design point: "the Chrome extension is the permanent escape hatch." Refresh this file at the end of your session. |
| `docs/todo.md` | Lines 12-15 are unchecked v0.1 validation items, including "Test 10 varied URLs" and "Confirm no duplicate saves for the same URL". The second one is now known to be false in exactly the way section 2.1 describes. Lines 46-51 are the parking lot; "LinkedIn saved posts bulk harvesting" sits there. |
| `docs/decision-log.md` | 2026-07-19 entry at line 109, "Capture Strategy | Browser-side capture extension replaces server-only fetching for blocked sites". Line 116, "Dedup | Canonical URL identity per source, not just tracking-param stripping". Both are directly on point; add a new dated entry when you make a real decision. |
| `docs/architecture.md` | Line 22 states the extension contract: "Sends {url, title, content} of the rendered page to /add with the Bearer token." Line 15 documents the `process_url(url, content=None)` passthrough. Everything below line 28 is historical v0.1 material about a deleted `app.py`; do not plan from it. |
| `docs/worklog.md` | Lines 111-124 are the 2026-09-02 security pass. Lines 125-139 are the 2026-09-03 migration fix and are the most important prose in the repo for this task; read them in full. |
| `docs/roadmap.md` | The Killed list. See section 1. |
| `README.md` | Lines 33-41 describe the capture surfaces. Lines 123-127 describe network exposure. Lines 131-138 are the user-facing setup for the Shortcut and the extension; **update line 138 if the install or upgrade steps change.** Lines 190-194 describe the deploy mechanism. |

---

## 6. Every capture path that exists today

Do not duplicate a path that already works. Two of these four are healthy.

### 6.1 Chrome extension (broken for feeds; the subject of this brief)

Sends: `POST {server}/add`, JSON `{url, title, content}` for a page capture or
`{url}` for a link right-click. Auth: `Authorization: Bearer <token>` from
`chrome.storage.local`. Loaded unpacked from `extension/`, extension id
`kphfomagphdipejgdklombahlncgcloi`, currently version 0.5.1.

Reliability: works for a single article or video page. Fails for anything inside
a feed, for the reasons in section 2. It is also the only path that can capture
a logged-in-only page, because it sends the rendered DOM text rather than asking
the server to fetch. That property must survive the rewrite.

### 6.2 iPhone Shortcut (works; leave it alone)

Documented in `README.md` lines 131-136: a Get Contents of URL action, `POST` to
`/add`, header `Authorization: Bearer <token>`, body JSON with key `url`. Sends
the URL only, no content, so the server fetches.

This is the source of every `lnkd.in/p/...` row in the inbox: 51 of 265. It
works because LinkedIn's mobile share sheet produces `lnkd.in/p/<code>`, which
redirects properly (section 2.2). Three captures on 2026-09-03 at 05:16, 05:17,
and 05:18 all became clean items within about 20 seconds each.

Reliability: high, with one documented fragility at `README.md` line 199: "The
Mac address changes across networks; update the iPhone shortcut if capture stops
working."

**The rewrite must not try to replace this.** If you build a popup URL field
(requirement M2), it complements the Shortcut on desktop; it does not supersede
it.

### 6.3 M4 menubar client, `client.py` (works)

141 lines. `add_url` (lines 97-124) opens an `osascript` dialog, validates the
`http://` or `https://` prefix, and POSTs `{"url": url}` to `{SERVER}/add` with
the bearer token, 15-second timeout, then posts a macOS notification. The token
is read from `secrets.json` at lines 18-22 and is never hardcoded. `SERVER`
comes from the gitignored `local_settings.py` (lines 12-15) and falls back to
`http://127.0.0.1:7778`. `view_kb` (lines 126-133) opens `/view?token=...` once,
which the server swaps for a session cookie.

Reliability: good. Same URL-only limitation as the Shortcut: it cannot capture a
logged-in page's content.

### 6.4 Server-side automatic re-capture (works, invisible)

`retry_loop` (`server.py` lines 882-901) every 6 hours retries `fetch` and `ai`
failures up to `MAX_AUTO_RETRIES = 3` (line 42) and re-queues up to 10
reconciled inbox orphans from `_reconcile_inbox` (lines 856-879). Only rows with
`authed: true` are re-queued. Note that of 265 inbox rows only 6 carry
`authed: true`, because the field was added on 2026-09-02 (commit `2d555fd`);
older rows have no field and are permanently ineligible. That is intended
behavior, not a bug to fix.

### 6.5 `/add_sync` (works, unused by any client)

`server.py` lines 1656-1665. Same ingest, synchronous, returns the real outcome.
Used today only from manual `curl` and tests. **This is the endpoint the rewritten
extension should use** if you want honest feedback; see requirement M5.

### 6.6 Deployment, so you know what pushing means

`README.md` lines 190-194: the always-on M1 runs a clone at
`~/content-digest-app` plus an auto-deploy LaunchAgent
(`com.shashank.autodeploy`) that fetches every 5 minutes, hard-resets to
upstream on change, runs `py_compile`, and restarts the server. **A push to
`main` deploys within 5 minutes.** Never edit code on the M1; the next cycle
overwrites it. The extension is loaded unpacked from the M4 working tree, so
extension changes take effect on reload, not on push.

---

## 7. The real requirements, ranked

Derived from section 2. Three cases must work, and only one works today.

- **Case A, a single article or video page.** Works today via the toolbar click.
- **Case B, an item inside a feed where the items are real anchors** (Reddit,
  Hacker News). The right-click link path sends `info.linkUrl`, which is
  correct, but sends no content, so the server must fetch, and it drops the
  page context entirely.
- **Case C, an item inside a feed where the items are not plain anchors**
  (LinkedIn). Completely broken. Both the icon click and the right-click store
  the feed URL; a right-click on an outbound anchor stores a redirector wrapper.

### Must-have

**M1. Correct URL identity for every capture.** The stored URL must identify the
thing being saved, never the container it was seen in. Concretely:

- Never send `location.href` when the user is saving an item inside a page.
- On LinkedIn, resolve to `linkedin.com/posts/<slug>` or
  `linkedin.com/feed/update/urn:li:activity:<id>`, the two shapes proven to work
  in section 2.3.
- If no item-level URL can be determined, **do not silently save the container
  URL.** Tell the user and offer the popup URL field instead. A refused capture
  the user can retry is strictly better than a wrong capture that poisons dedupe
  for that URL forever.

**M2. A popup with a URL field.** `manifest.json` gets a `default_popup`. The
popup needs, at minimum: a text field prefilled with the current tab URL, a Save
button, a "save this page with its text" action, and a visible result line. This
single change makes every site recoverable, because Shanky can always copy a
permalink from the post's own menu and paste it. It is the highest
value-per-line change in this brief.

**M3. Unwrap known redirector wrappers before sending.** Do this in the
extension, so the stored identity is right from the first byte. Wrappers to
handle, with the ones actually present in his data marked:

| Wrapper | In his inbox today | Unwrap rule |
|---|---|---|
| `linkedin.com/safety/go/?url=<enc>` | yes, 1 row | percent-decode the `url` parameter |
| `lnkd.in/<code>` | derived from the above | see the warning below |
| `lnkd.in/p/<code>` | yes, 51 rows | leave alone; the server resolves it correctly |
| `google.com/url?q=` or `?url=` | no | decode `q`, else `url` |
| `t.co/<code>` | no | already in `_SHORTENER_HOSTS`, `extractors.py` line 34 |
| `l.facebook.com/l.php?u=`, `out.reddit.com`, `href.li`, `away.vk.com` | no | build the table generically so adding one is a one-line change |

Also strip, or leave to the server: `utm_source` (141 rows), `utm_medium` (141),
`rcm` (141), `utm_campaign` (2), `lipi` (1), `isSdui` (1). The server already
strips `utm_*` and the LinkedIn set (`extractors.py` lines 54-64); do not
duplicate that logic, just do not fight it.

**Warning on `lnkd.in/<code>`:** unwrapping `safety/go` yields a `lnkd.in` short
code that the server cannot resolve (section 2.2, verified). Sending the
unwrapped `lnkd.in/<code>` alone is still a broken capture. Either resolve it in
the page, where the browser has the session and follows the interstitial's
client-side hop, or prefer the containing post's permalink over the outbound
link. Decide which and say why in `docs/decision-log.md`.

**M4. Make the selection context save the selection, with the right identity.**
Add an explicit `info.selectionText` branch in the context-menu handler so a
selection save is distinguishable from a page save, and pair it with an
item-level URL from M1, not `location.href`.

**M5. Visible, persistent, honest feedback.** The 4-second badge
(`background.js` line 79) is not enough, and it currently lies (defect D2). The
rewrite must:

- Use `/add_sync` (`server.py` lines 1656-1665) so the extension knows the real
  outcome: `saved`, `already_saved`, `failed` with a reason, or `invalid`.
- Surface `already_saved` distinctly from `saved`. Today's silent duplicate drop
  is the single worst failure mode.
- Show the outcome somewhere that persists: the popup, a short list of the last
  five captures with their outcomes, or both.
- Keep a badge for at-a-glance state, but do not make it the only channel.

**M6. Never discard a payload.** Remove the early return on 401 and 403
(`background.js` line 96). Queue it, mark it as needing configuration, and show
that in the popup. A capture Shanky made must never disappear because the token
was wrong.

### Nice-to-have

- **N1. LinkedIn item-URL extraction from the DOM.** Walk up from the
  right-click target to the nearest ancestor carrying the post URN (commonly a
  `data-urn` or `data-id` attribute holding `urn:li:activity:<id>`) and build
  `https://www.linkedin.com/feed/update/urn:li:activity:<id>/`. Section 2.3
  proves that URL shape summarizes correctly. **Inference: I could not verify
  the current LinkedIn DOM attribute names, because driving Chrome was out of
  scope for this audit. Verify them live before relying on them, and fall back
  to M2's popup field when the walk finds nothing.**
- **N2. In-page credentialed resolution of `lnkd.in/<code>`.** A `fetch` from
  the content script inherits the user's session and follows the interstitial;
  the server cannot. Only worth it if N1 is not sufficient.
- **N3. A Test connection button in the options page.** One `GET {server}/health`
  (`server.py` lines 1500-1505, unauthenticated, returns `{"ok": true,
  "processing": ...}`) plus one authenticated `GET {server}/failures` (lines
  1506-1514, returns 401 without a valid token) tells the user in one click
  whether the URL and the token are both right. This directly prevents a repeat
  of the 0.5.0 incident.
- **N4. Show the pending queue depth** in the popup so a queued capture is
  visible rather than a vanished amber `Q`.

### Later

- A keyboard shortcut via a `commands` block in the manifest.
- Narrower host permissions once injection is `activeTab`-triggered only.
- Firefox or Safari ports.

### Explicitly out of bounds

- Anything from v0.2, v0.3, or v1 (`CLAUDE.md` lines 42-52).
- LinkedIn saved-posts bulk harvesting (`docs/roadmap.md`, Killed list).
- A build step, a bundler, a framework, or an npm dependency.
- Rewriting `server.py`, `extractors.py`, or `client.py` beyond what a capture
  requirement forces. If a server change is genuinely required, propose it
  separately with its own justification.

---

## 8. What must not regress

Every item here was added on 2026-09-02 or 2026-09-03 and each one closed a real
incident. Preserve all of them.

1. **The token lives in `chrome.storage.local` and never in
   `chrome.storage.sync`.** `background.js` lines 11-16 and `options.js` lines
   6-23. The reason is recorded in `docs/worklog.md` line 120: the bearer token
   was replicating to the Google account through Chrome sync.
2. **The migration must survive.** `background.js` lines 112-168. It is guarded
   by `migratedFromSync`, it never clobbers a value the user has typed since the
   upgrade, and it calls `chrome.storage.sync.clear()` unconditionally once the
   copy is written. If you restructure `background.js`, carry this forward
   intact, keep the guard key name so it does not re-run, and keep the
   unconditional clear.
3. **The 15-minute `chrome.alarms` retry queue.** `background.js` lines 21-22,
   35-55. Added because a capture made while the tailnet was down used to vanish
   (`docs/worklog.md` line 120, incident dated 2026-08-31 in the code comment at
   `background.js` line 20). The queue is capped at 100 entries. Keep the cap.
4. **Bearer auth on every POST.** `background.js` line 28 sends it; `server.py`
   lines 1391-1394 and 1592-1594 enforce it. Never send a capture unauthenticated
   and never fall back to a query-parameter token.
5. **Server-side SSRF and size caps.** `server.py` lines 122-123 and 150-185,
   `extractors.py` lines 39-47. Do not send payloads that require raising
   `MAX_BODY_BYTES`; the current 20,000-character cap in `grabPageContent`
   (`background.js` line 72) is well inside the 1 MB POST limit and should stay
   that way.
6. **The migration lesson, stated so you do not repeat it.**
   - A storage-location change is not a fix until the **old location is
     purged**. Commit `2d555fd` (2026-09-02) moved every read from
     `chrome.storage.sync` to `chrome.storage.local` and shipped no migration.
     The token stayed in sync, still replicating. Moving the read without
     deleting the write location closed nothing.
   - The same commit silently reset the server URL, because `storage.local` was
     empty on upgrade and both the options page and the service worker fell back
     to `DEFAULTS.server = "http://localhost:7778"`. Nothing errored. Captures
     just started failing against a server that was not there.
   - Commit `2daa57c` (2026-09-03) added the guarded migration. It worked, and it
     **still did not fix the server URL**, because "local always wins"
     (`background.js` line 134) treats the non-empty string `http://localhost:7778`
     as a value the user chose. Shanky had to retype the address by hand.
     **Design rule for the rewrite: a defaulted value and a user-chosen value must
     be distinguishable.** Store `server` as unset until the user sets it, and
     apply the default at read time, or store a `configuredAt` marker alongside
     it. Do not make a hardcoded default indistinguishable from a real setting.
   - **A migration in an unpacked extension only fires if the manifest version is
     bumped.** `chrome.runtime.onInstalled` with reason `update` requires a
     version change; a plain Reload on the same version does not fire it. If your
     rewrite ships an `onInstalled` migration, bump `manifest.json` line 4 in the
     same change, and say so in the test plan.

Verified state on the M4 as of 2026-09-03 09:45, so you know the starting point
is clean:

```
$ ls ~/Library/Application\ Support/Google/Chrome/Default/Local\ Extension\ Settings/kphfomagphdipejgdklombahlncgcloi/
000003.log  CURRENT  LOCK  LOG  LOG.old  MANIFEST-000001

$ ls ~/Library/Application\ Support/Google/Chrome/Default/Sync\ Extension\ Settings/kphfomagphdipejgdklombahlncgcloi
No such file or directory
```

Key names present in the local store (values deliberately not printed):
`migratedFromSync`, `server`, `token`, `pending`. The sync store directory is
gone, which is the migration's success signal.

---

## 9. How to test without guessing

All commands are read-only. Replace `$CD_SERVER` with the tailnet address, which
lives in the gitignored `config.json` (`server_base`) and `local_settings.py`
(`SERVER`). Do not write that address into any tracked file.

### 9.1 Is the server up

```bash
curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 "$CD_SERVER/health"
# expect 200
```

### 9.2 Check auth without printing the token

```bash
cd ~/Projects-with-Claude/content-digest-app
TOKEN=$(python3 -c 'import json;print(json.load(open("secrets.json"))["auth_token"])')
echo "token length: ${#TOKEN}"                        # expect 64
curl -s -o /dev/null -w 'no auth   -> %{http_code}\n' --max-time 8 "$CD_SERVER/failures"
curl -s -o /dev/null -w 'bad token -> %{http_code}\n' --max-time 8 -H 'Authorization: Bearer wrong' "$CD_SERVER/failures"
curl -s -o /dev/null -w 'good tok  -> %{http_code}\n' --max-time 8 -H "Authorization: Bearer $TOKEN" "$CD_SERVER/failures"
```

Observed on 2026-09-03: `401`, `401`, `200`. Never `echo "$TOKEN"`.

### 9.3 Did a capture land, and what became of it

```bash
ssh m1 'cd ~/content-digest-app && python3 -c "
import json
d=json.load(open(\"inbox.json\"))
for i in d[\"items\"][:10]:
    print(i[\"received_at\"], i.get(\"authed\"), i[\"url\"][:110])
"'
```

Every row carries `url`, `received_at`, and `authed` (`server.py` lines 601-617).
A row appearing here means the POST reached the server; it does **not** mean the
item was saved. To find out what happened next:

```bash
ssh m1 'cd ~/content-digest-app && python3 -c "
import json
k=json.load(open(\"knowledge.json\"))
print(\"saved:\", len(k[\"items\"]))
for i in k[\"items\"][:5]:
    print(i[\"saved_at\"], i[\"url\"][:90], \"|\", i.get(\"title\",\"\")[:60])
"'

ssh m1 'cd ~/content-digest-app && python3 -c "
import json
f=json.load(open(\"failures.json\"))
for x in f.get(\"items\",[]):
    print(x[\"url\"][:90], x.get(\"error_type\"), str(x.get(\"error_reason\"))[:70])
"'
```

**A URL in `inbox.json` that is in neither `knowledge.json` nor `failures.json`
was silently dropped**, almost always by the `already_saved` branch
(`server.py` lines 675-678). That is the check that caught the 08:50:42 failure.

### 9.4 Read the extension's Chrome storage on disk

```bash
EXT=kphfomagphdipejgdklombahlncgcloi
D="$HOME/Library/Application Support/Google/Chrome/Default/Local Extension Settings/$EXT"
ls -la "$D"
# key names only, values never printed:
strings "$D"/*.log "$D"/*.ldb 2>/dev/null | grep -oE 'migratedFromSync|server|token|pending' | sort | uniq -c
# the sync store must not exist:
ls "$HOME/Library/Application Support/Google/Chrome/Default/Sync Extension Settings/$EXT"
```

The LevelDB store is written lazily, so close Chrome or wait a few seconds after
a settings change before reading. Never dump raw values; the token is in there.

### 9.5 Syntax checks before you reload anything

```bash
cd ~/Projects-with-Claude/content-digest-app
node --check extension/background.js
node --check extension/options.js
python3 -m json.tool extension/manifest.json > /dev/null && echo "manifest ok"
```

These are the same checks recorded in `docs/worklog.md` line 139 for 0.5.1.

### 9.6 Acceptance tests the rewrite must pass

Run each one, record the `inbox.json` row, the `knowledge.json` or
`failures.json` outcome, and the feedback the extension showed. Do not mark a
test passed on the basis of a green badge; a green badge is exactly what the
08:50:42 failure produced.

| # | Scenario | Pass condition |
|---|---|---|
| T1 | Toolbar save on a plain article | Stored URL equals the article URL; item appears in `knowledge.json` with a real title. This works today; it must not regress. |
| T2 | Toolbar save on a YouTube watch page | Stored URL is the canonical `watch?v=` form; item saved or a clear transcript-missing failure. |
| T3 | **Toolbar click while on `https://www.linkedin.com/feed/`** | The extension must **not** store `https://www.linkedin.com/feed/`. Either it resolves an item-level URL, or it refuses and tells the user to use the popup. This is the 08:49:18 case. |
| T4 | **Right-click on a LinkedIn feed post body, not an anchor** | Same as T3. This is the 08:50:42 case. Additionally: two consecutive attempts must never produce one silent no-op. |
| T5 | **Right-click a LinkedIn outbound anchor whose href is `linkedin.com/safety/go/?url=...`** | The stored URL is the unwrapped destination or the containing post permalink, never the wrapper. This is the 08:51:59 case; today it lands in `failures.json`. |
| T6 | Right-click a real anchor on Reddit or Hacker News | Stored URL is the anchor's destination, normalized. |
| T7 | Select text on a LinkedIn post, right-click, Save | Selection text is stored as the content **and** the URL is the post, not `/feed/`. |
| T8 | Paste a permalink into the popup and Save | Item saved under exactly that URL. |
| T9 | Save the same URL twice | The second attempt reports `already_saved` visibly. Nothing is silently dropped. |
| T10 | Save with a deliberately wrong token | The capture is queued, not discarded, and the user is told the token is wrong. Restore the token, flush, and confirm the capture lands. |
| T11 | Save with the server unreachable (stop the tailnet or point at a dead port) | The capture is queued; the alarm flushes it within 15 minutes once reachable; the queue depth is visible. |
| T12 | Fresh install into a clean Chrome profile | Options are empty, not silently defaulted to a `localhost` that looks configured. |
| T13 | Upgrade from 0.5.1 with a token and a real server URL already in `storage.local` | Both values survive untouched; `migratedFromSync` stays set; the sync store stays absent. |
| T14 | Toolbar click on a `chrome://` page | A clear message, not a silent no-op (defect D8). |
| T15 | Bump the manifest version and reload unpacked | No "duplicate id cd-save" error in the service worker console (defect D7). |

---

## 10. Open questions and what I could not verify

State these in your report rather than assuming them away.

1. **The LinkedIn DOM attribute that carries the post URN.** N1 depends on it. I
   did not drive Chrome for this audit, so the attribute names are inference.
   Verify live, and build the fallback to M2's popup field so a DOM change
   degrades to something usable rather than to a wrong save.
2. **Whether `capture(tab)` from the context menu actually picks up the active
   selection.** Reading `background.js` lines 60-61 and 183 says it does when the
   selection exceeds 80 characters. Confirm in the browser before you rely on it
   either way.
3. **The 2026-09-17 measurement window** is not in any repo file. See section
   1.1. Confirm the date with Shanky before you plan around it.
4. **Whether the two `/feed/` inbox rows should be cleaned up.** A poisoned
   `https://www.linkedin.com/feed/` item currently sits in `knowledge.json` from
   08:49:32 and will keep absorbing future feed captures through the
   `already_saved` branch until it is deleted. Deleting it is a `POST /delete`
   with the bearer token (`server.py` lines 1607-1616). **Ask Shanky before
   deleting anything from his live knowledge base.** Do not do it unprompted.
5. **`/add` is not a real route** (`server.py` lines 1667-1670). Every client
   currently posts to it and it works by fallthrough. Decide whether the rewrite
   should move to `/add_sync`, and record the decision; do not quietly change the
   server's routing.
