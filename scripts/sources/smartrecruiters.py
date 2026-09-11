"""SmartRecruiters — free public postings API (no key).

    list   : https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset=N
    detail : https://api.smartrecruiters.com/v1/companies/{token}/postings/{id}

Several smaller cruise and hotel-operations employers run here. Unknown tokens
return an empty list rather than an error, so the token list is safe to expand.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

API = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
PAGE = 100
SLEEP = 0.3


def _cfg() -> list[dict]:
    return json.load(open(common.EMPLOYERS, encoding="utf-8")).get("smartrecruiters", [])


def _text_of(section: dict) -> str:
    """SmartRecruiters nests description text under jobAd.sections.*.text."""
    return (section or {}).get("text", "") or ""


def fetch() -> list[dict]:
    records: list[dict] = []
    for emp in _cfg():
        token, name = emp["token"], emp["name"]
        offset, got = 0, 0
        while offset < 1000:
            data = common.get_json(API.format(token=token),
                                   params={"limit": PAGE, "offset": offset})
            if not data or not data.get("content"):
                break
            for p in data["content"]:
                title = p.get("name", "")
                loc = p.get("location") or {}
                loc_s = ", ".join(filter(None, [loc.get("city", ""),
                                                loc.get("region", ""),
                                                loc.get("country", "").upper()]))
                if not common.classify_housekeeping(title=title):
                    continue
                det = common.get_json(f"{API.format(token=token)}/{p.get('id','')}")
                secs = ((det or {}).get("jobAd") or {}).get("sections") or {}
                desc = "\n\n".join(filter(None, [
                    _text_of(secs.get("companyDescription")),
                    _text_of(secs.get("jobDescription")),
                    _text_of(secs.get("qualifications")),
                    _text_of(secs.get("additionalInformation"))]))
                rec = common.build_record(
                    source="smartrecruiters", company=name, brand=emp.get("brand", ""),
                    title=title, location=loc_s,
                    department=(p.get("department") or {}).get("label", ""),
                    apply_url=(p.get("ref") or {}).get("jobAd", "")
                              or f"https://jobs.smartrecruiters.com/{token}/{p.get('id','')}",
                    date_posted=p.get("releasedDate", ""),
                    description_html=desc)
                if rec:
                    records.append(rec)
                    got += 1
                time.sleep(SLEEP)
            offset += PAGE
            if len(data["content"]) < PAGE:
                break
            time.sleep(SLEEP)
        print(f"  smartrecruiters/{name:20s} {got} housekeeping records")
    print(f"  smartrecruiters: {len(records)} records")
    return records


def covered() -> set[tuple[str, str]]:
    return {("smartrecruiters", e["name"]) for e in _cfg()}


if __name__ == "__main__":
    for r in fetch():
        print(r["title"], "|", r["company"], "|", r["match_verdict"])
