"""Telegram — public channel previews (no key, no login, no browser).

`https://t.me/s/<channel>` serves a plain-HTML preview of a public channel, so
unlike Instagram this one is fully automatable.

Honest note on yield: the reachable cruise/seafarer channels are dominated by
cargo and merchant-navy postings and by agents asking candidates to send CVs,
not by cruise housekeeping vacancies. It is wired in because it costs little
and occasionally carries a real lead — not because it is a rich source.

Output is LEADS, scored by trust.py — never verified jobs.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402
import trust as trust_mod  # noqa: E402

_MSG = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time datetime="([^"]+)"')
SLEEP = 0.4


def _channels() -> list[str]:
    cfg = json.load(open(common.EMPLOYERS, encoding="utf-8"))
    return cfg.get("telegram", [])


def fetch() -> list[dict]:
    leads: list[dict] = []
    for ch in _channels():
        html_text = common.get_text(f"https://t.me/s/{ch}")
        if not html_text:
            continue
        msgs = _MSG.findall(html_text)
        times = _TIME.findall(html_text)
        for i, m in enumerate(msgs):
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m))).strip()
            if len(text) < 40:
                continue
            if not re.search(r"(housekeep|stateroom|cabin steward|room steward|"
                             r"laundry|linen|cleaner|utility|public area|steward)",
                             text, re.I):
                continue
            if not re.search(r"(cruise|ship|vessel|onboard|shipboard|fleet)", text, re.I):
                continue
            tr = trust_mod.assess_trust(text, source="telegram", account=ch)
            leads.append({
                "lead_id": common.make_job_id("telegram", ch, text[:80], str(i)),
                "source": "telegram", "account": ch,
                "url": f"https://t.me/s/{ch}",
                "text": text[:2000],
                "date_posted": common.parse_date(times[i][:10]) if i < len(times) else "",
                "captured_on": common.TODAY,
                **tr,
            })
        time.sleep(SLEEP)
    print(f"  telegram: {len(leads)} housekeeping leads from {len(_channels())} channels")
    return leads


if __name__ == "__main__":
    for l in fetch():
        print(f"  [{l['band']:9s} risk {l['risk']:3d}] {l['text'][:90]}")
