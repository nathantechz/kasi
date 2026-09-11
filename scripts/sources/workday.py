#!/usr/bin/env python3
"""Workday — public CXS job-search API (no key).

Verified live for:
    nclh.wd108.myworkdayjobs.com  tenant 'nclh'  sites NCLH_Careers, POA_Careers, ...
    red.wd1.myworkdayjobs.com     tenant 'red'   site  VV   (Virgin Voyages)

    list   : POST https://{host}/wday/cxs/{tenant}/{site}/jobs
             {"appliedFacets":{},"limit":20,"offset":N,"searchText":""}
    detail : GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}
             → jobPostingInfo.jobDescription (HTML) + startDate
    apply  : https://{host}/{site}{externalPath}

Workday reports `postedOn` as a relative string ("Posted 6 Days Ago"), which
common.parse_date() converts to a real date.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

PAGE = 20
MAX_PAGES = 25
SLEEP = 0.35


def _cfg() -> list[dict]:
    return json.load(open(common.EMPLOYERS, encoding="utf-8")).get("workday", [])


def _detail(host: str, tenant: str, site: str, path: str) -> dict:
    url = f"https://{host}/wday/cxs/{tenant}/{site}{path}"
    d = common.get_json(url, headers={"Referer": f"https://{host}/{site}"})
    info = (d or {}).get("jobPostingInfo") or {}
    return {
        "description_html": info.get("jobDescription", ""),
        "start_date": info.get("startDate", "") or info.get("postedOn", ""),
        "end_date": info.get("endDate", ""),
        "location": info.get("location", ""),
        "time_type": info.get("timeType", ""),
    }


def fetch(*, want_detail: bool = True) -> list[dict]:
    records: list[dict] = []
    reached: set[tuple[str, str]] = set()

    for emp in _cfg():
        host, tenant, site = emp["host"], emp["tenant"], emp["site"]
        name, hint = emp["name"], emp.get("hint")
        ship_pat = re.compile(emp["ship_location_pattern"], re.I) if emp.get("ship_location_pattern") else None
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        got = 0

        for page in range(MAX_PAGES):
            payload = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE,
                       "searchText": ""}
            data = common.post_json(url, payload,
                                    headers={"Referer": f"https://{host}/{site}"})
            if not data:
                break
            postings = data.get("jobPostings") or []
            if not postings:
                break
            reached.add(("workday", name))

            for j in postings:
                title = j.get("title", "")
                loc = j.get("locationsText", "") or ""
                path = j.get("externalPath", "")
                apply_url = f"https://{host}/{site}{path}" if path else ""

                # Only spend a detail request on postings that could plausibly
                # matter — housekeeping-ish titles. Everything else is recorded
                # from list data alone.
                looks_hk = common.classify_housekeeping(title=title)
                det = {}
                if want_detail and looks_hk and path:
                    det = _detail(host, tenant, site, path)
                    time.sleep(SLEEP)

                # Per-site hint wins; otherwise a brand-name location means a ship.
                h = hint
                if h is None and ship_pat and ship_pat.search(loc):
                    h = "ship"

                rec = common.build_record(
                    source="workday", company=name, brand=emp.get("brand", ""),
                    title=title, location=det.get("location") or loc,
                    apply_url=apply_url,
                    date_posted=j.get("postedOn", "") or det.get("start_date", ""),
                    description_html=det.get("description_html", ""),
                    shipboard_hint=h,
                )
                if rec:
                    records.append(rec)
                    got += 1

            if len(postings) < PAGE:
                break
            time.sleep(SLEEP)

        print(f"  workday/{site:24s} {got:4d} postings  ({name})")

    print(f"  workday: {len(records)} records from {len(reached)} boards")
    return records


def covered() -> set[tuple[str, str]]:
    return {("workday", e["name"]) for e in _cfg()}


if __name__ == "__main__":
    for r in fetch():
        if r["housekeeping"]:
            print(r["title"], "|", r["location"], "|ship=", r["shipboard"],
                  "|", r["match_verdict"], r["match_score"])
