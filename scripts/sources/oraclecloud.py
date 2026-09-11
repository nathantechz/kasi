"""Oracle Recruiting Cloud (Fusion HCM) — Holland America Group.

Carnival's Holland America Group brands (Princess, Holland America, Seabourn,
Cunard, P&O) all sit on one Oracle tenant:

    list   : GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
             ?onlyData=true
             &expand=requisitionList.secondaryLocations
             &finder=findReqs;siteNumber={site},limit=N,offset=M,keyword=...
    detail : same resource with finder=findReqDetailsById;requisitionId=...,siteNumber=...
    apply  : https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{id}

Two things worth knowing about this API:
  * `expand=requisitionList...` is REQUIRED. Without it the response still
    carries TotalJobsCount but `requisitionList` comes back empty, which looks
    exactly like "no results" — a silent, very easy bug to ship.
  * The keyword finder matches the description too, so a keyword sweep returns
    plenty of unrelated titles. The housekeeping gate still decides.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

SLEEP = 0.4
PAGE = 100
MAX_DETAIL = 60


def _cfg() -> tuple[list[dict], list[str]]:
    d = json.load(open(common.EMPLOYERS, encoding="utf-8"))
    return d.get("oraclecloud", []), d.get("_housekeeping_keywords", [])


def _api(host: str) -> str:
    return f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"


def _search(host: str, site: str, keyword: str, offset: int) -> tuple[int, list[dict]]:
    finder = (f"findReqs;siteNumber={site},limit={PAGE},offset={offset},"
              f"sortBy=POSTING_DATES_DESC")
    if keyword:
        finder += f",keyword={keyword}"
    d = common.get_json(_api(host), params={
        "onlyData": "true",
        "expand": "requisitionList.secondaryLocations",   # REQUIRED — see docstring
        "finder": finder})
    if not d or not d.get("items"):
        return 0, []
    it = d["items"][0]
    return int(it.get("TotalJobsCount") or 0), (it.get("requisitionList") or [])


def _detail(host: str, site: str, req_id: str) -> str:
    d = common.get_json(_api(host), params={
        "onlyData": "true", "expand": "all",
        "finder": f"findReqDetailsById;requisitionId={req_id},siteNumber={site}"})
    if not d or not d.get("items"):
        return ""
    return (d["items"][0] or {}).get("ExternalDescriptionStr", "") or ""


def fetch() -> list[dict]:
    employers, keywords = _cfg()
    records: list[dict] = []

    for emp in employers:
        host, site, name = emp["host"], emp["site"], emp["name"]
        seen: dict[str, dict] = {}

        for kw in keywords:
            total, jobs = _search(host, site, kw, 0)
            for j in jobs:
                rid = str(j.get("Id") or "")
                if rid:
                    seen.setdefault(rid, j)
            # page on only when the keyword really has more than one page
            off = PAGE
            while off < min(total, 300):
                _, more = _search(host, site, kw, off)
                if not more:
                    break
                for j in more:
                    rid = str(j.get("Id") or "")
                    if rid:
                        seen.setdefault(rid, j)
                off += PAGE
                time.sleep(SLEEP)
            time.sleep(SLEEP)

        detailed = 0
        for rid, j in seen.items():
            title = j.get("Title", "")
            if not common.classify_housekeeping(title=title):
                continue
            desc = ""
            if detailed < MAX_DETAIL:
                desc = _detail(host, site, rid)
                detailed += 1
                time.sleep(SLEEP)
            rec = common.build_record(
                source="oraclecloud", company=name, brand=emp.get("brand", ""),
                title=title, location=j.get("PrimaryLocation", "") or "",
                apply_url=(f"https://{host}/hcmUI/CandidateExperience/en/sites/"
                           f"{site}/job/{rid}"),
                date_posted=j.get("PostedDate", ""),
                description_html=desc,
                shipboard_hint=emp.get("hint"))
            if rec:
                records.append(rec)

        print(f"  oraclecloud/{name:24s} {len(seen):4d} unique seen → {detailed} housekeeping detailed")

    print(f"  oraclecloud: {len(records)} records")
    return records


def covered() -> set[tuple[str, str]]:
    employers, _ = _cfg()
    return {("oraclecloud", e["name"]) for e in employers}


if __name__ == "__main__":
    for r in fetch():
        print(r["match_score"], r["match_verdict"], "ship=", r["shipboard"], "|",
              r["title"], "|", r["location"])
