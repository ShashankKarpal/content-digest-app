# docs/worklog.md

## Worklog — Content Digest App

Append a dated note after every major session. Keep entries concise.

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
