#!/usr/bin/env python3
"""
Content Digest: Morning Brief
Sends a daily email summary of items saved in the last 24 hours.
Runs at 7am Dubai time via LaunchAgent.
"""

import hmac
import json
import smtplib
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "config.json"
KNOWLEDGE_FILE = APP_DIR / "knowledge.json"
LOG_FILE = APP_DIR / "daily_brief.log"
SECRETS_FILE = APP_DIR / "secrets.json"
RESURFACE_FILE = APP_DIR / "resurface.json"
LAST_RENDER_FILE = APP_DIR / "brief_last.html"

DUBAI_OFFSET = timezone(timedelta(hours=4))

CATEGORY_ORDER = ["News", "Work", "Learning", "Ideas", "Entertainment"]

# Resurfacing (feature 1): every brief pulls up to RESURFACE_MAX items back out
# of the backlog with one-tap triage links. Pure arithmetic scorer by design:
# the M1 has no RAM headroom for model calls (audit 2026-08-17, addendum A4).
RESURFACE_MAX = 3
RESURFACE_COOLDOWN_DAYS = 5   # do not nag about the same item on consecutive days
RESURFACE_STRIKES = 3         # after 3 ignored resurfacings, decay archives it
TRIAGE_EXPIRY_HOURS = 72      # signed links go stale after 3 days


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


def load_auth_token():
    try:
        token = json.loads(SECRETS_FILE.read_text()).get("auth_token", "")
        return "" if token in ("NEW_TOKEN", "YOUR_TOKEN_HERE") else token
    except Exception:
        return ""


def load_resurface():
    try:
        return json.loads(RESURFACE_FILE.read_text()) if RESURFACE_FILE.exists() else {}
    except Exception:
        return {}


def _parse_saved_at(item):
    try:
        t = datetime.fromisoformat(item.get("saved_at", ""))
    except (ValueError, TypeError):
        return None
    return t.replace(tzinfo=DUBAI_OFFSET) if t.tzinfo is None else t


def _sign_triage(token, url, state, expires):
    """Mirror of server.py _sign_triage; keep them identical."""
    msg = f"{url}|{state}|{expires}".encode()
    return hmac.new(token.encode(), b"triage-v1:" + msg, "sha256").hexdigest()


def triage_link(base, token, url, state, expires):
    sig = _sign_triage(token, url, state, expires)
    return f"{base}/triage?u={quote(url, safe='')}&s={state}&e={expires}&sig={sig}"


def pick_resurfaced(items, resurface, now, limit=RESURFACE_MAX):
    """Pure-arithmetic backlog selection: score = age_days * relevance,
    act-marked items first, at most one item per category while choice lasts.
    Skips items saved in the last 24h (they are in the new-saves section),
    items on resurface cooldown, and items already at the strike limit.
    Shared with the /view triage deck (server.py imports this; limit=10 there)
    so the brief and the deck rank from one scorer and one fatigue ledger."""
    cutoff_24h = now - timedelta(hours=24)
    cands = []
    for it in items:
        st = it.get("state", "")
        if st == "archive":
            continue
        saved = _parse_saved_at(it)
        if saved is None or saved >= cutoff_24h:
            continue
        r = resurface.get(it["url"], {})
        if st == "" and r.get("count", 0) >= RESURFACE_STRIKES:
            continue  # decay will archive it; stop nagging
        last = r.get("last")
        if last and st != "act":
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=DUBAI_OFFSET)
                if (now - last_dt).days < RESURFACE_COOLDOWN_DAYS:
                    continue
            except ValueError:
                pass
        age_days = max((now - saved).days, 1)
        score = age_days * int(it.get("relevance", 3) or 3)
        cands.append((st == "act", score, it))
    cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
    picked, seen_cats = [], set()
    for _, _, it in cands:
        if len(picked) >= limit:
            break
        if it.get("category") in seen_cats:
            continue
        picked.append(it)
        seen_cats.add(it.get("category"))
    for _, _, it in cands:  # fill remaining slots if diversity left gaps
        if len(picked) >= limit:
            break
        if it not in picked:
            picked.append(it)
    return picked


def aged_out_last_24h(items, now):
    cutoff = now - timedelta(hours=24)
    out = []
    for i in items:
        ts = i.get("auto_archived_at")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=DUBAI_OFFSET)
        if t >= cutoff:
            out.append(i)
    return out


def save_resurface(resurface, picked, now):
    for it in picked:
        r = resurface.setdefault(it["url"], {"count": 0})
        r["count"] = r.get("count", 0) + 1
        r["last"] = now.isoformat()
    tmp = RESURFACE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(resurface, indent=2))
    tmp.rename(RESURFACE_FILE)


def group_by_category(items):
    grouped = defaultdict(list)
    for item in items:
        cat = item.get("category", "Ideas")
        grouped[cat].append(item)
    ordered = {}
    for cat in CATEGORY_ORDER:
        if cat in grouped:
            ordered[cat] = grouped[cat]
    for cat in grouped:
        if cat not in ordered:
            ordered[cat] = grouped[cat]
    return ordered


def format_resurfaced_section(picked, base, token, now):
    """The triage section: up to RESURFACE_MAX backlog items, each with
    one-tap signed Act / Later / Archive links."""
    import html as html_mod
    if not picked or not token:
        return ""
    expires = int(now.timestamp()) + TRIAGE_EXPIRY_HOURS * 3600
    cards = ""
    for item in picked:
        title = html_mod.escape(item.get("title", "Untitled"))
        summary = html_mod.escape(item.get("summary", ""))[:280]
        url = item.get("url", "")
        saved = _parse_saved_at(item)
        age = f"{(now - saved).days}d ago" if saved else ""
        cat = html_mod.escape(item.get("category", ""))
        buttons = ""
        for state, label, color in (
                ("act", "Act", "#c83232"),
                ("revisit", "Later", "#3B82F6"),
                ("archive", "Archive", "#4B5563")):
            link = triage_link(base, token, url, state, expires)
            buttons += (f'<a href="{html_mod.escape(link)}" style="display:inline-block;'
                        f'background:{color};color:#fff;padding:8px 18px;border-radius:6px;'
                        f'font-size:13px;font-weight:bold;text-decoration:none;'
                        f'font-family:Arial,sans-serif;margin-right:8px;">{label}</a>')
        cards += f'''
<div style="background:#16213e;border-left:3px solid #ff9f1c;border-radius:8px;padding:20px;margin:12px 0;font-family:Arial,sans-serif;">
  <div style="font-size:15px;font-weight:bold;color:#F8FAFC;margin-bottom:4px;"><a href="{html_mod.escape(url)}" style="color:#F8FAFC;text-decoration:none;">{title}</a></div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:10px;">{cat} &nbsp;|&nbsp; saved {age}</div>
  <div style="font-size:13px;color:#CBD5E1;line-height:1.6;margin-bottom:14px;">{summary}</div>
  <div>{buttons}</div>
</div>'''
    return f'''<div style="margin:28px 0 8px 0;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;color:#ff9f1c;letter-spacing:1px;">FROM YOUR BACKLOG ({len(picked)})</div>
<div style="font-size:12px;color:#9CA3AF;font-family:Arial,sans-serif;margin-bottom:4px;">One tap decides. Links work on your tailnet and expire in {TRIAGE_EXPIRY_HOURS} hours.</div>
{cards}'''


def format_email_body(grouped, send_date, resurfaced_html="", aged_count=0):
    """Generate HTML email body matching the Content Digest dark theme."""
    from collections import Counter
    import html as html_mod

    total = sum(len(items) for items in grouped.values())
    save_word = "save" if total == 1 else "saves"

    CAT_COLORS = {
        "Work": "#F97316",
        "Learning": "#3B82F6",
        "Entertainment": "#A855F7",
        "News": "#EF4444",
        "Ideas": "#F97316",
    }

    # Header stats
    cat_summary = ""
    if total > 1:
        cat_pills = ""
        for cat, items in grouped.items():
            color = CAT_COLORS.get(cat, "#F97316")
            cat_pills += f'''<span style="display:inline-block;background:{color};color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;margin:0 6px 6px 0;font-family:Arial,sans-serif;">{html_mod.escape(cat)}: {len(items)}</span>'''
        cat_summary = f'''<div style="margin:16px 0 8px 0;">{cat_pills}</div>'''

        all_tags = []
        for items_list in grouped.values():
            for item in items_list:
                all_tags.extend(item.get("tags", []))
        if all_tags:
            top_tags = [tag for tag, _ in Counter(all_tags).most_common(6)]
            tag_str = ", ".join(top_tags)
            cat_summary += f'''<div style="color:#9CA3AF;font-size:12px;font-family:Arial,sans-serif;margin-top:8px;">Top tags: {html_mod.escape(tag_str)}</div>'''

    # Build item cards
    cards_html = ""
    item_counter = 0
    for category, items in grouped.items():
        color = CAT_COLORS.get(category, "#F97316")
        cards_html += f'''<div style="margin:24px 0 8px 0;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;color:#D1D5DB;letter-spacing:1px;">{html_mod.escape(category.upper())} ({len(items)})</div>'''

        for item in items:
            item_counter += 1
            title = html_mod.escape(item.get("title", "Untitled"))
            summary = html_mod.escape(item.get("summary", ""))
            url = item.get("url", "")
            url_escaped = html_mod.escape(url)
            tags = item.get("tags", [])
            relevance = item.get("relevance", 3)
            action_points = item.get("action_points", [])
            saved_at_str = item.get("saved_at", "")

            time_str = ""
            if saved_at_str:
                try:
                    saved_dt = datetime.fromisoformat(saved_at_str)
                    if saved_dt.tzinfo is None:
                        saved_dt = saved_dt.replace(tzinfo=DUBAI_OFFSET)
                    time_str = saved_dt.strftime("%I:%M %p").lstrip("0")
                except ValueError:
                    pass

            # Meta line
            meta_parts = []
            if time_str:
                meta_parts.append(time_str)
            rel_dots = "&#9679;" * relevance + "&#9675;" * (5 - relevance)
            meta_parts.append(rel_dots)
            meta_str = " &nbsp;|&nbsp; ".join(meta_parts)

            # Tags
            tag_pills = ""
            for t in tags[:5]:
                tag_pills += f'''<span style="display:inline-block;background:#374151;color:#D1D5DB;padding:3px 10px;border-radius:10px;font-size:11px;margin:0 4px 4px 0;">{html_mod.escape(t)}</span>'''

            # Action points
            ap_html = ""
            if action_points:
                ap_items = ""
                for ap in action_points:
                    ap_items += f'''<li style="color:#D1D5DB;font-size:13px;margin-bottom:4px;font-family:Arial,sans-serif;">{html_mod.escape(ap)}</li>'''
                ap_html = f'''<div style="margin-top:12px;"><div style="color:{color};font-size:12px;font-weight:bold;font-family:Arial,sans-serif;margin-bottom:6px;">Action Pointers</div><ul style="margin:0;padding-left:20px;">{ap_items}</ul></div>'''

            # Item state pill (act / revisit / archive from the review loop)
            state = item.get("state", "")
            STATE_STYLES = {
                "act": ("#c83232", "ACT ON THIS"),
                "revisit": ("#3B82F6", "REVISIT LATER"),
            }
            state_pill = ""
            if state in STATE_STYLES:
                s_color, s_label = STATE_STYLES[state]
                state_pill = f'''<span style="display:inline-block;background:{s_color};color:#fff;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:bold;margin-right:8px;">{s_label}</span>'''

            cards_html += f'''
<div style="background:#1E293B;border-left:3px solid {color};border-radius:8px;padding:20px;margin:12px 0;font-family:Arial,sans-serif;">
  <div style="font-size:16px;font-weight:bold;color:#F8FAFC;margin-bottom:4px;">{title}</div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:12px;">
    {state_pill}<span style="display:inline-block;background:{color};color:#fff;padding:2px 8px;border-radius:8px;font-size:11px;margin-right:8px;">{html_mod.escape(category)}</span>
    {meta_str}
  </div>
  <div style="font-size:13px;color:#CBD5E1;line-height:1.6;margin-bottom:12px;">{summary}</div>
  {ap_html}
  <div style="margin-top:12px;">{tag_pills}</div>
  <div style="margin-top:14px;">
    <a href="{url_escaped}" style="display:inline-block;background:{color};color:#fff;padding:8px 18px;border-radius:6px;font-size:13px;font-weight:bold;text-decoration:none;font-family:Arial,sans-serif;">Read Article &#8594;</a>
  </div>
</div>'''

    body = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#0F172A;">
<div style="max-width:640px;margin:0 auto;padding:24px 16px;background-color:#0F172A;">

  <div style="text-align:center;margin-bottom:24px;">
    <div style="font-size:28px;font-weight:bold;color:#F97316;font-family:Arial,sans-serif;">Content Digest</div>
    <div style="font-size:14px;color:#9CA3AF;font-family:Arial,sans-serif;margin-top:4px;">{send_date.strftime("%A, %B %d, %Y")}</div>
  </div>

  <div style="background:#1E293B;border-radius:12px;padding:20px;text-align:center;margin-bottom:24px;">
    <div style="font-size:36px;font-weight:bold;color:#F8FAFC;font-family:Arial,sans-serif;">{total}</div>
    <div style="font-size:14px;color:#9CA3AF;font-family:Arial,sans-serif;">{save_word} in the last 24 hours</div>
    {cat_summary}
    {f'<div style="font-size:12px;color:#6B7280;font-family:Arial,sans-serif;margin-top:10px;">{aged_count} item{"" if aged_count == 1 else "s"} aged out of the backlog automatically</div>' if aged_count else ''}
  </div>

  {resurfaced_html}

  {cards_html}

  <div style="text-align:center;margin-top:32px;padding-top:20px;border-top:1px solid #374151;">
    <div style="font-size:11px;color:#6B7280;font-family:Arial,sans-serif;">Sent by Content Digest, locally from your Mac.</div>
  </div>

</div>
</body>
</html>'''
    return body


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


def format_empty_email_body(send_date, total_items):
    """HTML body when no items saved in last 24h."""
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
    <div style="font-size:14px;color:#9CA3AF;line-height:1.6;">Your knowledge base has <strong style="color:#F97316;">{total_items}</strong> total items. Save something today to keep building.</div>
  </div>
  <div style="text-align:center;margin-top:24px;font-size:12px;color:#64748B;">
    Sent daily at 7:00 AM Dubai time
  </div>
</div>
</body>
</html>"""


def main():
    dry_run = "--dry-run" in sys.argv
    log("Daily brief started." + (" (dry run)" if dry_run else ""))
    try:
        config = load_config()
        data = load_knowledge()
        all_items = data.get("items", [])
        recent = filter_last_24h(all_items)
        send_date = datetime.now(DUBAI_OFFSET)

        token = load_auth_token()
        base = config.get("server_base", "http://localhost:7778")
        resurface = load_resurface()
        picked = pick_resurfaced(all_items, resurface, send_date) if token else []
        aged = aged_out_last_24h(all_items, send_date)
        resurfaced_html = format_resurfaced_section(picked, base, token, send_date)

        if recent or picked or aged:
            grouped = group_by_category(recent)
            parts = [f"{len(recent)} saves"]
            if picked:
                parts.append(f"{len(picked)} to triage")
            subject = f"Content Digest, {send_date.strftime('%A %B %d')}: " + ", ".join(parts)
            body = format_email_body(grouped, send_date,
                                     resurfaced_html=resurfaced_html,
                                     aged_count=len(aged))
        else:
            subject = f"Content Digest, {send_date.strftime('%A %B %d')}: no new saves"
            body = format_empty_email_body(send_date, len(all_items))

        try:
            LAST_RENDER_FILE.write_text(body)
        except Exception:
            pass

        if dry_run:
            log(f"Dry run: rendered {len(recent)} saves, {len(picked)} resurfaced, "
                f"{len(aged)} aged out. Wrote {LAST_RENDER_FILE.name}; nothing sent.")
            return 0

        send_email(config, subject, body)
        if picked:
            save_resurface(resurface, picked, send_date)
        log(f"Sent brief with {len(recent)} items, {len(picked)} resurfaced, "
            f"{len(aged)} aged out, to {config['recipient']}.")
        return 0

    except Exception as e:
        log(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
