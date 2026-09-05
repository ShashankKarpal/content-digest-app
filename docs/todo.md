# docs/todo.md

## Task List: Content Digest App

Rewritten 2026-09-05. Version history lives in roadmap.md and worklog.md; this
file holds only what is open.

## Measurement phase (until about 2026-09-17), owner

- [x] Reload the Chrome extension to 0.6.1 (2026-09-05).
- [ ] iPhone Shortcut: add the header `X-Client: shortcut` (the status notification step already exists).
- [ ] Tap at least one Act / Later / Archive link in a 07:00 brief so the first real `triage_log.jsonl` line exists.
- [ ] Monday 2026-09-07: confirm the brief carries the "Loop this week" line and `loopcheck-history.txt` on the host gained its first row; then retire the external weekly SSH loop check.
- [ ] Live extension tests still not run (automated coverage only): wrong or removed token, changed server address, clean-profile uninstall and reinstall migration, deleting the historical `/feed/` knowledge item.
- [ ] Browser-capture the two authwalled links still in the failures list (Patreon post, one LinkedIn post) via the extension.
- [ ] Decide whether to clear the three 2026-09-03 extension-test rows from the failures list (LinkedIn safety/go wrapper, signup/cold-join, one posts/activity).
- [ ] Optional: remove the unread `send_hour_dubai` and `send_minute_dubai` keys from the host `config.json` (the brief time is the LaunchAgent's).

## After the read

- [ ] The 2026-09-17 read: two paths, see current-phase.md and roadmap.md (parked list, or the pivot clause).
- [ ] If the loop is kept: add `bind_addresses` to the host `config.json` (loopback, tailnet address, home LAN address), verify with `lsof -nP -iTCP:7778 -sTCP:LISTEN`, confirm the phone still saves from both networks.
- [ ] Move hardcoded values (port, model names, TTLs) into a config file.

## Screenshots to refresh in README (owner takes, then rephrase and commit)

- [ ] `screenshots/menubar-menu-mac.png`: menu open, showing the Server status row.
- [ ] `screenshots/extension-popup-chrome.png`: the 0.6.1 popup, empty field, Ready.
- [ ] `screenshots/extension-options-chrome.png`: options with a green Test connection result.
- [ ] `screenshots/brief-iphone.png`: a morning brief in Mail with the backlog triage buttons.
- [ ] `screenshots/brief-monday-loop-line.png`: the Monday brief with the "Loop this week" line (after 2026-09-07).
- [ ] `screenshots/triage-deck-mac.png`: one deck card open on the knowledge base.

## Historical checklists

The v0.1 checklist (10-URL test, iPhone shortcut end to end, dedupe confirmation, Karl sign-off) and the v0.4 deploy list were superseded by the 2026-08-17 red team audit and the v0.5 ship; see roadmap.md "Delivered" sections and `redteam-audit-2026-08-17.md`. Killed items (topic clustering, LinkedIn bulk harvesting, Notion or Obsidian export, multi-user digest) are listed in roadmap.md and are not to be resurrected without new evidence.
