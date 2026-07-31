#!/usr/bin/env python3
"""One-shot verification of the junk-item fixes (2026-07-31).
Run: python3 test_fix_verification.py  (stdlib only, safe to delete after)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from extractors import normalize_url, get_extractor, fetch_linkedin_content

FAILING_LINKS = [
    "https://lnkd.in/p/etUQuMCH",
    "https://lnkd.in/p/dxb9VYuc",
    "https://lnkd.in/p/e5nqX3V2",
    "https://lnkd.in/p/dJ-z_iwW",
    "https://www.linkedin.com/posts/imujahid_mcp-webmcp-mcpabrapps-ugcPost-7482375429887250432-772V/",
]

print("=" * 70)
print("1. normalize_url resolves lnkd.in to canonical linkedin.com URLs")
print("=" * 70)
for u in FAILING_LINKS:
    n = normalize_url(u)
    ok = "lnkd.in" not in n and "linkedin.com" in n
    print(("OK  " if ok else "FAIL"), u, "->", n[:90])

print()
print("=" * 70)
print("2. get_extractor routes linkedin/lnkd.in to the dedicated extractor")
print("=" * 70)
for u in FAILING_LINKS + ["https://blog.cloudflare.com/a-primer-on-proxies/"]:
    fn, exclusive = get_extractor(normalize_url(u))
    name = fn.__name__ if fn else "generic(trafilatura)"
    print(f"{name:28s} exclusive={exclusive}  {normalize_url(u)[:70]}")

print()
print("=" * 70)
print("3. fetch_linkedin_content returns real post text (not authwall)")
print("=" * 70)
bad_markers = ("agree & join", "check your browser", "redirected", "user agreement")
for u in FAILING_LINKS:
    text = fetch_linkedin_content(u)
    if not text:
        print("CLEAN-FAIL (None returned; would be a recorded failure, not junk):", u)
        continue
    low = text.lower()
    junk = [m for m in bad_markers if m in low]
    status = "OK  " if not junk and len(text) > 150 else f"JUNK {junk}"
    print(status, u)
    print("     ", text[:140].replace("\n", " | "))
print()
print("Done. Delete this file after verification.")
