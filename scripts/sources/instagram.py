"""Instagram — cruise recruiters who post vacancies as graphics.

A lot of Indian cruise hiring is advertised on Instagram by agents and crewing
companies rather than on any ATS. Two things make it usable:

1. **The vacancy list is in the image, not the caption.** Captions are often
   just "Vacancies for Indonesians". The positions are printed on the graphic.
2. **Meta OCRs the graphic for us.** Every post image carries an accessibility
   `alt` attribute containing Meta's own transcription:
   *"May be a graphic of text that says \"VIKING WE'RE HIRING! ... 1ST
   HOUSEKEEPER -ASST CHIEF HOUSEKEEPER -STATEROOM STEWARD\""*.
   So no OCR or vision model is needed — just read the alt text.

The catch: that alt text is injected client-side, so `requests` cannot see it
(a plain fetch of a post returns a 624 KB JavaScript shell with no alt, no
og:description and no caption). Capturing it needs a real browser.

So this adapter does NOT scrape live. It ingests snapshots under
`data/informal/instagram_*.json`, which are captured with a browser — see
`scripts/capture_instagram.md`. That keeps the pipeline honest: it never
pretends to have fetched something it could not.

Everything from here is a LEAD, not a job. Leads are scored by trust.py and
kept in a separate table; they are never mixed into the verified `jobs` table.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402
import trust as trust_mod  # noqa: E402

SNAP_DIR = os.path.join(common.DATA, "informal")

# "May be a graphic of text that says "....""  → the transcribed graphic
_ALT_TEXT = re.compile(r'that says\s*[""“"]?(.*)', re.S)
_ALT_PREFIX = re.compile(r'^(Photo|Video|Image) by .*?on \w+ \d+, \d{4}\.\s*', re.I)
_DATE = re.compile(r'on (\w+ \d{1,2}, \d{4})')

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _alt_to_text(alt: str) -> str:
    """Strip Meta's wrapper, keep the transcribed words."""
    body = _ALT_PREFIX.sub("", alt or "")
    m = _ALT_TEXT.search(body)
    text = m.group(1) if m else body
    text = text.strip().strip('".”“ ')
    return re.sub(r"\s+", " ", text)


def _alt_to_date(alt: str) -> str:
    m = _DATE.search(alt or "")
    if not m:
        return ""
    try:
        month, day, year = re.match(r"(\w+) (\d{1,2}), (\d{4})", m.group(1)).groups()
        return f"{year}-{_MONTHS[month.lower()]:02d}-{int(day):02d}"
    except Exception:
        return ""


def _snapshots() -> list[dict]:
    posts: list[dict] = []
    for path in sorted(glob.glob(os.path.join(SNAP_DIR, "instagram_*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                posts.extend(json.load(fh).get("posts", []))
        except Exception:
            continue
    return posts


def fetch() -> list[dict]:
    posts = _snapshots()
    if not posts:
        print("  instagram: no snapshots in data/informal/ — see scripts/capture_instagram.md")
        return []

    leads: list[dict] = []
    for p in posts:
        text = _alt_to_text(p.get("alt", ""))
        if len(text) < 25:
            continue
        # Same housekeeping gate as every other source — an Instagram post about
        # a fishing-shop vacancy is not a cruise housekeeping lead.
        if not re.search(
                r"(housekeep|stateroom|cabin steward|room steward|laundry|linen|"
                r"cleaner|utility|public area|accommodation|steward)", text, re.I):
            continue
        tr = trust_mod.assess_trust(text, source="instagram",
                                    account=p.get("account", ""))
        leads.append({
            "lead_id": common.make_job_id("instagram", p.get("account", ""),
                                          text[:80], p.get("url", "")),
            "source": "instagram",
            "account": p.get("account", ""),
            "url": p.get("url", ""),
            "text": text[:2000],
            "date_posted": _alt_to_date(p.get("alt", "")),
            "captured_on": p.get("captured_on", ""),
            **tr,
        })
    print(f"  instagram: {len(posts)} posts in snapshots → {len(leads)} housekeeping leads")
    return leads


if __name__ == "__main__":
    for l in fetch():
        print(f"  [{l['band']:9s} risk {l['risk']:3d}] {l['text'][:80]}")
