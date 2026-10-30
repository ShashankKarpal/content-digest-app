# docs/todo.md

## Task List: Content Digest App

Rewritten 2026-10-22 for v0.6 (decision 14). Version history lives in
roadmap.md and worklog.md; this file holds only what is open.

## Now, owner

- [x] Live checks with the owner at the keyboard (2026-10-22): the four
      extension tests (wrong token, changed server address, clean-profile
      install, the historical `/feed/` item deleted) pass, and a signed-in
      LinkedIn save passes. Patreon not tested (no membership). The extension
      reaches the server; it was missing from `/health` clients only because
      it had not been used since 2026-09-05.
- [ ] Optional: remove the unread `send_hour_dubai`, `send_minute_dubai` and
      `server_base` keys from the host `config.json` (the brief time is the
      LaunchAgent's; triage links are retired).

## Next, code (found in the 2026-10-22 live checks)

- [x] Extension popup: on a 401 say the token was rejected; today it shows the
      same "server is unavailable or needs attention" text as a network failure.
- [ ] Extension queue: an item refused for a bad token retries every 15 minutes
      forever; stop retrying, or retry only after the settings change.
- [ ] Extension errors page: "Cannot create item with duplicate id cd-save".
      `createMenu` runs from both `onInstalled` and `onStartup` and the
      `removeAll` callback races; harmless, the menu works.

## Parked

- [ ] `bind_addresses` in the host `config.json` (loopback, tailnet address,
      home LAN address). Parked 2026-10-22 by owner delegation: every request
      already needs the token and passes the source allowlist, a home LAN
      address can change and silently drop Wi-Fi capture, and the check needs
      the phone on both networks. Revisit only with a new reason.
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
