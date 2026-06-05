#!/usr/bin/env python3
"""
Content Digest: Morning Brief
Sends a daily email summary of items saved in the last 24 hours.
Runs at 7am Dubai time via LaunchAgent.
"""

import json
import smtplib
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / "config.json"
KNOWLEDGE_FILE = APP_DIR / "knowledge.json"
LOG_FILE = APP_DIR / "daily_brief.log"

DUBAI_OFFSET = timezone(timedelta(hours=4))

CATEGORY_ORDER = ["News", "Work", "Learning", "Ideas", "Entertainment"]


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


def format_email_body(grouped, send_date):
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

            cards_html += f'''
<div style="background:#1E293B;border-left:3px solid {color};border-radius:8px;padding:20px;margin:12px 0;font-family:Arial,sans-serif;">
  <div style="font-size:16px;font-weight:bold;color:#F8FAFC;margin-bottom:4px;">{title}</div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:12px;">
    <span style="display:inline-block;background:{color};color:#fff;padding:2px 8px;border-radius:8px;font-size:11px;margin-right:8px;">{html_mod.escape(category)}</span>
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
  </div>

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


def main():
    log("Daily brief started.")
    try:
        config = load_config()
        data = load_knowledge()
        recent = filter_last_24h(data.get("items", []))

        if not recent:
            log("No items in last 24 hours. Skipping send.")
            return 0

        grouped = group_by_category(recent)
        send_date = datetime.now(DUBAI_OFFSET)
        subject = f"Content Digest, {send_date.strftime('%A %B %d')}: {len(recent)} saves"
        body = format_email_body(grouped, send_date)

        send_email(config, subject, body)
        log(f"Sent brief with {len(recent)} items to {config['recipient']}.")
        return 0

    except Exception as e:
        log(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
