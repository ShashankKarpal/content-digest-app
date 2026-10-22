# docs/todo.md

## Task List: Content Digest App

Rewritten 2026-10-22 for v0.6 (decision 14). Version history lives in
roadmap.md and worklog.md; this file holds only what is open.

## Now, owner

- [ ] Live checks with the owner at the keyboard: the four extension tests
      (wrong or removed token, changed server address, clean-profile reinstall
      migration, the historical `/feed/` knowledge item) and two login-walled
      saves. Run them from the Cowork live-checks prompt
      (`11-COWORK-content-digest-live-checks.md` in the owner's task pack);
      its steps about the old failure rows and the deleted loop-check task are
      already done.
- [ ] First check that the Chrome extension reaches the server at all: `/health`
      has never listed an `extension` client since client tracking began
      (2026-09-05).
- [ ] Optional: remove the unread `send_hour_dubai`, `send_minute_dubai` and
      `server_base` keys from the host `config.json` (the brief time is the
      LaunchAgent's; triage links are retired).

## After the live checks

- [ ] Add `bind_addresses` to the host `config.json` (loopback, tailnet address,
      home LAN address), verify with `lsof -nP -iTCP:7778 -sTCP:LISTEN`, confirm
      the phone still saves from both networks.
- [ ] Move hardcoded values (port, model names, retry intervals) into a config file.

## Screenshots to refresh in README (owner takes, then rephrase and commit)

- [ ] `screenshots/knowledge-base-mac.png` and `knowledge-base-iphone.png`: the
      v0.6 cards (no Act / Later / Archive buttons; a Tool filter).
- [ ] `screenshots/menubar-menu-mac.png`: menu open, showing the Server status row.
- [ ] `screenshots/extension-popup-chrome.png`: the 0.6.1 popup, empty field, Ready.
- [ ] `screenshots/extension-options-chrome.png`: options with a green Test connection result.
- [ ] `screenshots/brief-iphone.png`: a slim morning brief in Mail.

## Historical checklists

The v0.1 checklist (10-URL test, iPhone shortcut end to end, dedupe confirmation, Karl sign-off) and the v0.4 deploy list were superseded by the 2026-08-17 red team audit and the v0.5 ship; see roadmap.md "Delivered" sections and `redteam-audit-2026-08-17.md`. The v0.5 measurement-phase list (triage taps, the Monday loop line) was retired with decision 14. Killed items (topic clustering, LinkedIn bulk harvesting, Notion or Obsidian export, multi-user digest) are listed in roadmap.md and are not to be resurrected without new evidence.
