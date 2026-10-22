#!/usr/bin/env python3
"""One-time data migrations, run by the server at start-up.

Each migration has an id and a function that changes the loaded items in
place and returns its counts. run() applies the pending ones in order:

1. backs up knowledge.json and failures.json next to them as
   <name>.pre-migration-<YYYYmmdd-HHMMSS>.bak (the repo's *.bak rule keeps
   them out of git) and checks each copy is byte-identical before going on,
2. applies every pending migration to one in-memory copy of knowledge.json,
3. writes knowledge.json once (atomic replace), then the marker.

The marker (migrations.json in the data folder) records each id with its time,
counts and backup names, so a second start does nothing. Each migration is
also idempotent by content: run again on migrated data, it changes nothing.
Any error leaves knowledge.json as it was and writes no marker; the server
starts anyway and the next start tries again.
"""

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


MIGRATIONS = (
    ("2026-10-decay-restore", restore_decay_archived),
)


def _write_json_atomic(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.rename(path)


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

        data = json.loads(data_file.read_text())
        items = data.get("items", [])
        results = {}
        for mid, fn in pending:
            results[mid] = fn(items, now)
        _write_json_atomic(data_file, data)
    except Exception as e:
        log(f"[migrate] FAILED, knowledge.json untouched: {type(e).__name__}: {e}")
        return {}

    for mid, counts in results.items():
        applied[mid] = {"at": now.isoformat(), "counts": counts, "backups": backups}
        log(f"[migrate] {mid}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    log("[migrate] backups: " + (", ".join(backups) or "none"))
    _write_json_atomic(marker_file, marker)
    return results
