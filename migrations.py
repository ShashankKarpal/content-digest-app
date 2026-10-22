#!/usr/bin/env python3
"""One-time data migrations, run by the server at start-up.

Each migration has an id and a function that changes the loaded items in
place and returns its counts. run() applies the pending ones in order:

1. reads and parses knowledge.json and applies every pending migration to
   that in-memory copy; if either fails, nothing is written and no backup
   is made (the next start tries again),
2. backs up knowledge.json and failures.json next to them as
   <name>.pre-migration-<YYYYmmdd-HHMMSS>.bak (the repo's *.bak rule keeps
   them out of git) and checks each copy is byte-identical before going on,
3. writes knowledge.json once (atomic replace), then the marker.

The marker (migrations.json in the data folder) records each id with its time,
counts and backup names, so a second start does nothing. Each migration is
also idempotent by content: run again on migrated data, it changes nothing.
Any error leaves knowledge.json as it was and writes no marker; the server
starts anyway and the next start tries again.
"""

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=4))   # the host's zone, same as server.py
MARKER_NAME = "migrations.json"
BACKED_UP = ("knowledge.json", "failures.json")


def is_decay_archive(item):
    """Archived by the retired auto-archive decay, not by hand. Decay stamped
    auto_archived_at always and state_source "decay" since 2026-09-05; a hand
    archive carries another state_source (view, deck, triage-link, api)."""
    if item.get("state") != "archive":
        return False
    source = item.get("state_source")
    return source == "decay" or (not source and bool(item.get("auto_archived_at")))


def restore_decay_archived(items, now):
    """Decision 14 (2026-09-30): decay is off and every item it archived goes
    back to neutral, with restored_at and the old state kept in state_history.
    No other field changes. A hand archive stays as it is; the counts say how
    many there were before and after (0 and 0 on 2026-09-30)."""
    counts = {"items": len(items), "archived_before": 0, "decay_archived_before": 0,
              "manual_archive_before": 0, "restored": 0}
    stamp = now.isoformat()
    for item in items:
        if item.get("state") != "archive":
            continue
        counts["archived_before"] += 1
        if not is_decay_archive(item):
            counts["manual_archive_before"] += 1
            continue
        counts["decay_archived_before"] += 1
        history = item.get("state_history")
        history = list(history) if isinstance(history, list) else []
        history.append({"state": "archive",
                        "source": item.get("state_source") or "decay",
                        "changed_at": item.get("state_changed_at") or item.get("auto_archived_at"),
                        "auto_archived_at": item.get("auto_archived_at")})
        item["state_history"] = history
        item["state"] = ""
        item["restored_at"] = stamp
        counts["restored"] += 1
    counts["archived_after"] = sum(1 for i in items if i.get("state") == "archive")
    counts["manual_archive_after"] = sum(
        1 for i in items if i.get("state") == "archive" and not is_decay_archive(i))
    return counts


# SHA-256 of the stored (canonical) URL of each of the 48 items that the
# 2026-09-30 review of the last 100 saves marked BUILT: a tool, app, repo,
# extension or product someone built and linked. Hashes, not URLs: this
# repository is public, and the URLs would publish part of the reading list.
TOOL_URL_SHA256 = frozenset({
    "0a37e6a74b542c679ddf98b514c06d85c11ba5c06688bb3d93ab80f0cffd5db8",
    "0d918093bc1440b1a5ce9d8d10b17e54e7ab91a763c2b1210fc943be31a5ba91",
    "1dd7e101225d962023c7d7a526d9b2ad87bf4cc5df7a05680c563f7d000081b6",
    "2840b7c3fa365ed699049d00ec2e7fd19f1c0bb8f13636c323d03d9faa64e43f",
    "28f3c028aaa0e6f7e4da5287b6e68ff3e8f8022ed70c24b607fbd15dd3565709",
    "2d5ff686525fb7198f88c02484335f995239670812f03a3eabdd3107568cddcd",
    "2d6aeee222407d91be6b3e0b601e064e4dfb8d351b0c2bc56841f838d0e1964f",
    "2e26bd8ccd57c3b22d6ff1050e4724efea9d0acc16c0a8a63d9bbd032c1dffd0",
    "3004718d984c7d9a751c279b626fb568d25c08cfc1608f66b324551a65ca3b54",
    "3a00b40a1ddc4bef471633e1167b779e308e4a6e8a4081bccd089481d0afe0f9",
    "3c0bf23284500257733254b22e271978b02a94037329443e4cd49ab1231c5914",
    "3f69b70c30735a4c75845b2fa3cde8b2102fe95eeadaa2fe410e4cbeeada6c00",
    "4272c9482da70fe0604f839899ff3b204a30d624d9e42b926b295ebf8d8d7ef8",
    "435af6790ca072be21c8bdf670c6cbc9dfdff55b4cfa719468c49ba0a062d23f",
    "4e59f5ec5e1fdd7eed2742292fa28b57c9f32ae665fe1443c02b26b37a7e1bc9",
    "4e8bbb36ad091999b7f7121e3cd00150a506c111ecc6125bed496b3dd02e88f8",
    "5149f4b00c0589ec926625ba955be8dbe7161307a7a6b871b24b2dc2a7bed66d",
    "5966518880aa0a84a5c0f1612383ad7b4edb0db60c61589567e3fed2a7a1773e",
    "5a5379e84c85c40a394b979eb8d1d1728a3d2c6d7d672b9bbfe63376745c282c",
    "63cc6903181ba3f5b77276c026e50dd29b96c4eb4ce4e7e3fe8022789c36b1b0",
    "6bfa4f0da5c47fad1b7bbb5b06485d50a53667feb9b2092356d640acad654c25",
    "761a7fc1155e3224968af96d4cac20a84b24604a1292329edc6a3f0d9918010e",
    "79c0e9425c83ad394483ff70d700e95b183fc5adb9fc4fc9686f082bcd125f38",
    "7b2c06866dd2b093fe579292d0fb536f3edf95122b1d900f08f1704833d60890",
    "8107dabfa2f3dcc49b96797533fe33e3a8a3f77a593680943c3c8a47b766f5c6",
    "88fea0aae1dd510a538d7c683262de70c0a966290d5ce8b7c011788c6b3dd4f8",
    "9ce948c4cceacf0de9543c17ab59c54bf18a7eb0479834b64538c5f30216ac8f",
    "9e9abf855bbf3d648ae90b918d14f24f50191a0e563e1983d695eab83a450974",
    "a4d5f8ab5397a872a6b366dfb0284fe62fe29742464c5f396a0dd6d975d060bc",
    "aeeab56c04d4f5a04e5feec35000b39816d64dc97cfbd0914c56924a462d94ac",
    "b157c9a63f72bd3ae0a3e5be78454f84a7de503adbaa1d2f642cfe2f3fcad9a2",
    "b27ebe516ee67ac99eebe7dda9d55bc1e25a2d8278505d63e69eb6a3a92aed07",
    "b2d84afc490ac23e4afce192d35360f5bd02ad384edbf07a63fedaadc319f2ea",
    "c3637c30c03441f87bb2007992d406f33c08c401caa52a325b378205c3127dca",
    "c7d249086ee737c39fc4fb01b02a39846e3d7ea5ea9d46388d0632e0e933157c",
    "caca02ed4d7f3355750bd4b594e8c5d48aff79f9b8b7282c5894672af342dff6",
    "ceb86cddfd634c09e1877da4c3060ea92919a7feb2dd74dfef8e7d3d8f0bd011",
    "d6599181174677b135fc7d2806f50f40922ea90bd690bc7f86cf8bf887c1f930",
    "d680d46a2c279d0aa0d282f4eb85d76a3534599077d695efd99718f6cefdcfc2",
    "d95ceebbe3547eeed3c9b924f2371f292aca94573b20aa922d2f15d355803b26",
    "dd022a2f253da888eb1d76041f76d01fdd0bba3c6f8b14081949eb3e2e0ab54e",
    "e1cbb3a83b7e240d2849f6d69730d2789c8c943fe10dd803bf18ec1777af292c",
    "eb8672f38d170e2bf2aa34837740b7d61e4c6c83fc9278fed9eb062850b356bb",
    "f21ad3e8ff778fecffb253c2a145bd235e0acba9888b4bd624e5ec386275145c",
    "f54af6f6958477d0a9b92cd14729006a0908c9d7854ef5e442394e227baf1e83",
    "fad0bec4b89cd5f28d07c1ebb90103ad602c5dbb389a05e282cee70ffccd40b6",
    "fd62f6b538cf7de9f9116844d7978fe55e1b532507ebe62cda2a41a24613ef86",
    "fe4294f9cc0fddad7d5cd194b71f6c1fa21db0acebf8556b0dc6ae04475df230",
})


def recategorize_built_as_tool(items, now):
    """Decision 14: the new Tool category starts with the 48 BUILT items,
    matched by the hash of the stored URL. The old category is kept in
    category_history; an item already in Tool is left alone."""
    counts = {"listed": len(TOOL_URL_SHA256), "recategorized": 0, "already_tool": 0,
              "not_found": 0, "from": {}}
    found = set()
    for item in items:
        digest = hashlib.sha256(str(item.get("url", "")).encode()).hexdigest()
        if digest not in TOOL_URL_SHA256:
            continue
        found.add(digest)
        old = item.get("category")
        if old == "Tool":
            counts["already_tool"] += 1
            continue
        history = item.get("category_history")
        history = list(history) if isinstance(history, list) else []
        history.append({"category": old, "changed_at": now.isoformat(), "by": "2026-10-tool-category"})
        item["category_history"] = history
        item["category"] = "Tool"
        counts["recategorized"] += 1
        counts["from"][old] = counts["from"].get(old, 0) + 1
    counts["not_found"] = len(TOOL_URL_SHA256) - len(found)
    return counts


MIGRATIONS = (
    ("2026-10-decay-restore", restore_decay_archived),
    ("2026-10-tool-category", recategorize_built_as_tool),
)


def _write_json_atomic(path, payload):
    tmp = path.with_name(path.name + ".tmp")   # knowledge.json.tmp, never knowledge.tmp
    try:
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def run(base_dir, now=None, log=print):
    """Apply pending migrations to base_dir. Returns {id: counts} for the ones
    applied by this call ({} when nothing was pending or nothing was done)."""
    base = Path(base_dir)
    now = now or datetime.now(TZ)
    marker_file = base / MARKER_NAME
    try:
        marker = json.loads(marker_file.read_text()) if marker_file.exists() else {}
        applied = marker.setdefault("applied", {})
    except (ValueError, AttributeError):
        log(f"[migrate] {MARKER_NAME} is unreadable; nothing applied, data untouched")
        return {}
    pending = [(mid, fn) for mid, fn in MIGRATIONS if mid not in applied]
    if not pending:
        return {}

    data_file = base / "knowledge.json"
    if not data_file.exists():
        # A fresh install has nothing to migrate, and new code never creates
        # what these migrations repair, so they are recorded as done.
        for mid, _ in pending:
            applied[mid] = {"at": now.isoformat(), "counts": {"items": 0}, "backups": []}
        _write_json_atomic(marker_file, marker)
        log("[migrate] no knowledge.json; recorded " + ", ".join(m for m, _ in pending) + " as done")
        return {}

    try:
        # Parse before backing up: a malformed file must not leave a new pair
        # of backups at every restart (review, 2026-10).
        data = json.loads(data_file.read_text())
        items = data["items"]
        if not isinstance(items, list):
            raise ValueError("items is not a list")
    except Exception as e:
        log(f"[migrate] knowledge.json unreadable ({type(e).__name__}); nothing applied, no backup made")
        return {}

    try:
        # Apply on the in-memory copy first: data a migration cannot handle
        # (an item that is not an object) must leave no backups behind either
        # (review, 2026-10). The file on disk is still the original.
        results = {}
        for mid, fn in pending:
            results[mid] = fn(items, now)
    except Exception as e:
        log(f"[migrate] FAILED, nothing written and no backup made: {type(e).__name__}: {e}")
        return {}

    try:
        stamp = now.strftime("%Y%m%d-%H%M%S")
        backups = []
        for name in BACKED_UP:
            src = base / name
            if not src.exists():
                continue
            dst = base / f"{name}.pre-migration-{stamp}.bak"
            shutil.copy2(src, dst)
            if dst.read_bytes() != src.read_bytes():
                raise OSError(f"backup of {name} does not match the original")
            backups.append(dst.name)
        _write_json_atomic(data_file, data)
    except Exception as e:
        log(f"[migrate] FAILED while saving, knowledge.json untouched: {type(e).__name__}: {e}")
        return {}

    for mid, counts in results.items():
        applied[mid] = {"at": now.isoformat(), "counts": counts, "backups": backups}
        log(f"[migrate] {mid}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    log("[migrate] backups: " + (", ".join(backups) or "none"))
    _write_json_atomic(marker_file, marker)
    return results
