#!/usr/bin/env python3
"""
Content Digest: Morning Brief
Sends a daily email summary of items saved in the last 24 hours.
Runs at 7am Dubai time via LaunchAgent.

Slim since decision 14 (2026-09-30): yesterday's new saves (title, category,
a two-line summary, the link) and the host-health warning. Nothing else: the
backlog resurfacing, the Act / Later / Archive links and the weekly loop line
are retired.
"""

import json
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "config.json"
KNOWLEDGE_FILE = APP_DIR / "knowledge.json"
LOG_FILE = APP_DIR / "daily_brief.log"
LAST_RENDER_FILE = APP_DIR / "brief_last.html"
CLIENTS_FILE = APP_DIR / "clients.json"              # written by server.py: last authenticated contact per client
BRIEF_SENT_FILE = APP_DIR / "brief_sent.json"        # stamped after each successful send; server.py puts it in /health
HOST_HEALTH_STALE_HOURS = 48                         # brief warns when saves or client contact stop for this long
SUMMARY_CHARS = 200                                  # about two lines of a mail client

DUBAI_OFFSET = timezone(timedelta(hours=4))


def log(message):
    timestamp = datetime.now(DUBAI_OFFSET).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_knowledge():
    if not KNOWLEDGE_FILE.exists():
        return {"items": []}
    with open(KNOWLEDGE_FILE) as f:
        return json.load(f)


def filter_last_24h(items):
    """Items saved in the last 24 hours, based on saved_at ISO timestamp."""
    cutoff = datetime.now(DUBAI_OFFSET) - timedelta(hours=24)
    recent = []
    for item in items:
        if item.get("state") == "archive":
            continue
        saved_at_str = item.get("saved_at")
        if not saved_at_str:
            continue
        try:
            saved_at = datetime.fromisoformat(saved_at_str)
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=DUBAI_OFFSET)
            if saved_at >= cutoff:
                recent.append(item)
        except ValueError:
            continue
    return recent


def _parse_iso(value):
    try:
        t = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return t.replace(tzinfo=DUBAI_OFFSET) if t.tzinfo is None else t


# --- Host health (D1): the brief tells you when the capture path is silently dead ---

def load_clients():
    try:
        return json.loads(CLIENTS_FILE.read_text()) if CLIENTS_FILE.exists() else {}
    except Exception:
        return {}


def _latest(timestamps):
    best = None
    for value in timestamps:
        t = _parse_iso(value) if isinstance(value, str) else None
        if t is not None and (best is None or t > best):
            best = t
    return best


def host_health(items, clients, now, stale_hours=HOST_HEALTH_STALE_HOURS):
    """Hours since the last save and the last authenticated client contact.
    Stale when either gap reaches `stale_hours` (or has never happened)."""
    last_save = _latest(i.get("saved_at") for i in items if isinstance(i, dict))
    last_contact = _latest(clients.values()) if isinstance(clients, dict) else None
    save_gap = int((now - last_save).total_seconds() // 3600) if last_save else None
    contact_gap = int((now - last_contact).total_seconds() // 3600) if last_contact else None
    stale = (save_gap is None or save_gap >= stale_hours
             or contact_gap is None or contact_gap >= stale_hours)
    return {"last_save_at": last_save.isoformat() if last_save else None,
            "last_contact_at": last_contact.isoformat() if last_contact else None,
            "save_gap_hours": save_gap, "contact_gap_hours": contact_gap, "stale": stale}


def format_host_health_line(hh):
    """One warning line for the brief, empty when healthy."""
    import html as html_mod
    if not hh.get("stale"):
        return ""
    def gap(h):
        return "never" if h is None else f"{h} h ago"
    text = (f"Host health: last save {gap(hh['save_gap_hours'])}, "
            f"last client contact {gap(hh['contact_gap_hours'])}. "
            f"If you have been saving links, the capture path is down: check the phone and the Mac are on the private network.")
    return (f'<div style="font-size:12px;color:#F59E0B;font-family:Arial,sans-serif;'
            f'margin-top:10px;">{html_mod.escape(text)}</div>')


# --- The slim brief ---------------------------------------------------------

def two_lines(text, limit=SUMMARY_CHARS):
    """The summary cut to about two lines, at a word boundary."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "..."


def _newest_first(items):
    return sorted(items, key=lambda i: _parse_iso(i.get("saved_at")) or datetime.min.replace(tzinfo=DUBAI_OFFSET),
                  reverse=True)


def format_email_body(items, send_date, health_html=""):
    """HTML body: one card per new save (title linked to the item, category,
    two-line summary), newest first, under a count and the host-health line."""
    import html as html_mod
    total = len(items)
    cards = ""
    for item in _newest_first(items):
        url = str(item.get("url", ""))
        href = html_mod.escape(url if url.startswith(("http://", "https://")) else "#")
        title = html_mod.escape(item.get("title") or url or "Untitled")
        category = html_mod.escape(item.get("category", ""))
        summary = html_mod.escape(two_lines(item.get("summary", "")))
        cards += f'''
<div style="background:#1E293B;border-left:3px solid #B17E51;border-radius:8px;padding:16px 18px;margin:12px 0;font-family:Arial,sans-serif;">
  <a href="{href}" style="font-size:16px;font-weight:bold;color:#F8FAFC;text-decoration:none;">{title}</a>
  <div style="font-size:12px;color:#9CA3AF;margin:6px 0 8px 0;">{category}</div>
  <div style="font-size:13px;color:#CBD5E1;line-height:1.6;">{summary}</div>
</div>'''
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#0F172A;">
<div style="max-width:640px;margin:0 auto;padding:24px 16px;background-color:#0F172A;">
  <div style="text-align:center;margin-bottom:20px;">
    <div style="font-size:28px;font-weight:bold;color:#F97316;font-family:Arial,sans-serif;">Content Digest</div>
    <div style="font-size:14px;color:#9CA3AF;font-family:Arial,sans-serif;margin-top:4px;">{send_date.strftime("%A, %B %d, %Y")}</div>
  </div>
  <div style="background:#1E293B;border-radius:12px;padding:16px;text-align:center;margin-bottom:12px;">
    <div style="font-size:15px;color:#F8FAFC;font-family:Arial,sans-serif;">{total} new {"save" if total == 1 else "saves"} in the last 24 hours</div>
    {health_html}
  </div>
  {cards}
</div>
</body>
</html>'''


def format_empty_email_body(send_date, total_items, health_html=""):
    """HTML body when nothing was saved in the last 24 hours."""
    date_str = send_date.strftime("%A, %B %d, %Y")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background-color:#0F172A;font-family:Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:24px 16px;background-color:#0F172A;">
  <div style="text-align:center;margin-bottom:24px;">
    <div style="font-size:24px;font-weight:bold;color:#F97316;">Content Digest</div>
    <div style="font-size:14px;color:#9CA3AF;margin-top:4px;">{date_str}</div>
  </div>
  <div style="background:#1E293B;border-radius:12px;padding:24px;text-align:center;">
    <div style="font-size:18px;color:#F1F5F9;font-weight:bold;margin-bottom:12px;">No new saves in the last 24 hours</div>
    <div style="font-size:14px;color:#9CA3AF;line-height:1.6;">Your knowledge base has <strong style="color:#F97316;">{total_items}</strong> items.</div>
    {health_html}
  </div>
</div>
</body>
</html>"""


def send_email(config, subject, body):
    msg = MIMEMultipart("alternative")
    msg["From"] = config["smtp_user"]
    msg["To"] = config["recipient"]
    msg["Subject"] = subject
    plain_fallback = "Your Content Digest is ready. View this email in an HTML-capable client."
    msg.attach(MIMEText(plain_fallback, "plain"))
    msg.attach(MIMEText(body, "html"))

    password = config["smtp_password"].replace(" ", "")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config["smtp_user"], password)
        server.send_message(msg)


def stamp_brief_sent(at, items):
    """Record a successful send for /health, so a check outside the app can
    tell a brief that stopped from a quiet day. Called only after SMTP
    accepted the message; a failure to write it is logged, never raised."""
    try:
        tmp = BRIEF_SENT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": at.isoformat(), "items": items}))
        tmp.rename(BRIEF_SENT_FILE)
    except Exception as e:
        log(f"Brief-sent stamp not written: {type(e).__name__}: {e}")


def main():
    dry_run = "--dry-run" in sys.argv
    if "--weekly" in sys.argv:
        # The weekly loop check was retired with triage (decision 14). Exit
        # without sending, so an old caller of --weekly never mails a brief.
        log("The weekly loop check is retired; nothing to do.")
        return 0
    log("Daily brief started." + (" (dry run)" if dry_run else ""))
    try:
        config = load_config()
        all_items = load_knowledge().get("items", [])
        recent = filter_last_24h(all_items)
        send_date = datetime.now(DUBAI_OFFSET)

        # Host health (D1): warn when saves or client contact have stopped.
        health_html = ""
        try:
            hh = host_health(all_items, load_clients(), send_date)
            health_html = format_host_health_line(hh)
            if hh["stale"]:
                log(f"Host health stale: save gap {hh['save_gap_hours']} h, contact gap {hh['contact_gap_hours']} h.")
        except Exception as e:
            log(f"Host health skipped: {type(e).__name__}: {e}")

        day = send_date.strftime("%A %B %d")
        if recent:
            subject = f"Content Digest, {day}: {len(recent)} {'save' if len(recent) == 1 else 'saves'}"
            body = format_email_body(recent, send_date, health_html)
        else:
            subject = f"Content Digest, {day}: no new saves"
            body = format_empty_email_body(send_date, len(all_items), health_html)

        try:
            LAST_RENDER_FILE.write_text(body)
        except Exception:
            pass

        if dry_run:
            log(f"Dry run: rendered {len(recent)} saves. Wrote {LAST_RENDER_FILE.name}; nothing sent.")
            return 0

        send_email(config, subject, body)
        log(f"Sent brief with {len(recent)} items, to {config['recipient']}.")
        stamp_brief_sent(datetime.now(DUBAI_OFFSET), len(recent))
        return 0

    except Exception as e:
        log(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
