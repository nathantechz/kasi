"""Radancy / TalentBrew career sites — Carnival, Disney.

These sites expose a public AJAX search endpoint that returns job-card HTML:

    list   : https://{host}/search-jobs/results?CurrentPage=N&RecordsPerPage=15&...
    detail : https://{host}{href}  → schema.org JobPosting JSON-LD

Keyword filtering is honoured server-side on some tenants and ignored on others,
so we page the board and apply our own housekeeping gate client-side.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

MAX_PAGES = 40
RECORDS = 15
SLEEP = 0.35
MAX_DETAIL = 80

_CARD = re.compile(
    r'href="(/job/[^"]+)"[^>]*>.*?<h2[^>]*>(.*?)</h2>(.*?)(?=<li|</ul>)', re.S)
_LOC = re.compile(r'class="job-location"[^>]*>\s*(.*?)\s*<', re.S)
_CAT = re.compile(r'class="job-category"[^>]*>\s*(.*?)\s*<', re.S)
_TOTPAGES = re.compile(r'data-total-pages="(\d+)"')


def _cfg() -> list[dict]:
    return json.load(open(common.EMPLOYERS, encoding="utf-8")).get("radancy", [])


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _params(page: int, keyword: str) -> dict:
    return {"ActiveFacetID": 0, "CurrentPage": page, "RecordsPerPage": RECORDS,
            "Distance": 50, "RadiusUnitType": 0, "Keyword": keyword, "Location": "",
            "ShowRadius": "False", "IsPagination": "False", "CustomFacetName": "",
            "FacetTerm": "", "FacetType": 0,
            "SearchResultsModuleName": "Search Results",
            "SearchFiltersModuleName": "Search Filters",
            "SortCriteria": 0, "SortDirection": 0, "SearchType": 5}


def _detail(host: str, href: str) -> dict:
    html = common.get_text(f"https://{host}{href}")
    out = {"description_html": "", "date_posted": "", "location": ""}
    if not html:
        return out
    d = common.extract_jsonld_jobposting(html)
    if not d:
        return out
    out["description_html"] = d.get("description", "")
    out["date_posted"] = d.get("datePosted", "")
    out["location"] = common.jsonld_location(d)
    return out


def fetch() -> list[dict]:
    records: list[dict] = []

    for emp in _cfg():
        host, name = emp["host"], emp["name"]
        seen: dict[str, tuple[str, str, str]] = {}

        # These tenants IGNORE the Keyword parameter server-side (Carnival and
        # Disney both return the full board regardless), so sweeping the same
        # pages once per keyword is pure waste. Page the board once and let the
        # housekeeping gate filter client-side.
        for kw in [""]:
            for page in range(1, MAX_PAGES + 1):
                data = common.get_json(f"https://{host}/search-jobs/results",
                                       params=_params(page, kw),
                                       headers={"X-Requested-With": "XMLHttpRequest",
                                                "Referer": f"https://{host}/search-jobs"})
                if not data or "results" not in data:
                    break
                res = data["results"]
                cards = _CARD.findall(res)
                if not cards:
                    break
                for href, title, tail in cards:
                    t = _clean(title)
                    if not t or "results found" in t.lower():
                        continue
                    lm, cm = _LOC.search(tail), _CAT.search(tail)
                    seen.setdefault(href, (t, _clean(lm.group(1)) if lm else "",
                                           _clean(cm.group(1)) if cm else ""))
                tp = _TOTPAGES.search(res)
                if tp and page >= int(tp.group(1)):
                    break
                time.sleep(SLEEP)
            time.sleep(SLEEP)

        detailed = 0
        for href, (title, loc, cat) in seen.items():
            if not common.classify_housekeeping(title=title, category=cat):
                continue
            det = {"description_html": "", "date_posted": "", "location": ""}
            if detailed < MAX_DETAIL:
                det = _detail(host, href)
                detailed += 1
                time.sleep(SLEEP)
            rec = common.build_record(
                source="radancy", company=name, brand=emp.get("brand", ""),
                title=title, location=det.get("location") or loc,
                category=cat, apply_url=f"https://{host}{href}",
                date_posted=det.get("date_posted", ""),
                description_html=det.get("description_html", ""),
            )
            if rec:
                records.append(rec)

        print(f"  radancy/{name:24s} {len(seen):4d} unique seen → {detailed} housekeeping detailed")

    print(f"  radancy: {len(records)} records")
    return records


def covered() -> set[tuple[str, str]]:
    return {("radancy", e["name"]) for e in _cfg()}


if __name__ == "__main__":
    for r in fetch():
        print(r["match_score"], r["match_verdict"], r["shipboard"], "|", r["title"], "|", r["location"])
