"""Lever — free public postings API (no key).

    list : https://api.lever.co/v0/postings/{token}?mode=json

Returns every posting with its full description inline, so no detail fetch is
needed. Lindblad Expeditions (expedition ships) hosts here.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

API = "https://api.lever.co/v0/postings/{token}?mode=json"
SLEEP = 0.4


def _epoch_to_iso(ms) -> str:
    """Lever reports createdAt as epoch milliseconds."""
    if not ms:
        return ""
    try:
        return _dt.datetime.fromtimestamp(int(ms) / 1000, _dt.timezone.utc).date().isoformat()
    except Exception:
        return ""


def _cfg() -> list[dict]:
    return json.load(open(common.EMPLOYERS, encoding="utf-8")).get("lever", [])


def fetch() -> list[dict]:
    records: list[dict] = []
    for emp in _cfg():
        token, name = emp["token"], emp["name"]
        data = common.get_json(API.format(token=token))
        if not isinstance(data, list):
            print(f"  lever/{name:24s} unreachable")
            continue
        got = 0
        for j in data:
            title = j.get("text", "")
            cats = j.get("categories") or {}
            team = cats.get("team", "") or ""
            if not common.classify_housekeeping(title=title, department=team):
                continue
            desc = "\n\n".join(filter(None, [
                j.get("descriptionPlain", ""),
                "\n".join(s.get("text", "") for s in (j.get("lists") or [])),
                j.get("additionalPlain", "")]))
            rec = common.build_record(
                source="lever", company=name, brand=emp.get("brand", ""),
                title=title, location=cats.get("location", "") or "",
                department=team, category=cats.get("department", "") or "",
                apply_url=j.get("hostedUrl", "") or j.get("applyUrl", ""),
                date_posted=_epoch_to_iso(j.get("createdAt")),
                description_text=desc,
                shipboard_hint=emp.get("hint"))
            if rec:
                records.append(rec)
                got += 1
        print(f"  lever/{name:24s} {len(data):4d} postings → {got} housekeeping")
        time.sleep(SLEEP)
    print(f"  lever: {len(records)} records")
    return records


def covered() -> set[tuple[str, str]]:
    return {("lever", e["name"]) for e in _cfg()}


if __name__ == "__main__":
    for r in fetch():
        print(r["match_score"], r["match_verdict"], r["shipboard"], "|", r["title"])
