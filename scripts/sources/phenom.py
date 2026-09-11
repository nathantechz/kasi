"""Phenom People career sites — MSC Cruises and Viking.

Phenom renders its search results server-side and leaves the whole result set
in a JS global on the page:

    phApp.ddo = { eagerLoadRefineSearch: { data: { jobs: [...] }, totalHits: N } }

so we read the search page HTML and parse that object — no private API, no key.
Each job carries the fields we need to classify honestly:

    division              e.g. "Crew: On our Ships"   → shipboard evidence
    category / multi_category, crewProfessionalFamily  → housekeeping evidence
    postedDate            what the board advertises today
    dateCreated           when the req was really opened (→ 'evergreen' flag)

Detail pages carry schema.org JSON-LD with the full description, which is what
the experience parser needs.

We sweep a list of housekeeping keywords rather than paging the whole board:
these sites carry thousands of reqs and we only care about one department.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

SLEEP = 0.6
PAGE = 10
MAX_PAGES = 8          # per keyword
MAX_DETAIL = 120       # per employer

_DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*(?:phApp|</script>|window\.)", re.S)


def _apply_url(emp: dict, job: dict, posting_url: str) -> str:
    """Deep-link straight to the application form.

    Phenom exposes `jobSeqNo`, which is exactly what the Apply button passes to
    the apply flow — so we can skip the job page and land Kasi on the form.
    Falls back to the posting URL when the template or the id is missing.
    """
    tmpl = emp.get("apply_url_template", "")
    seq = str(job.get("jobSeqNo") or "")
    if tmpl and seq:
        return tmpl.replace("{jobSeqNo}", seq)
    return posting_url


def _cfg() -> tuple[list[dict], list[str]]:
    d = json.load(open(common.EMPLOYERS, encoding="utf-8"))
    return d.get("phenom", []), d.get("_housekeeping_keywords", [])


def _slug(title: str) -> str:
    """Phenom job-URL slug: 'OCEAN - Stateroom Steward/ess' → 'OCEAN-Stateroom-Stewardess'."""
    s = re.sub(r"[^A-Za-z0-9 \-]", "", title or "")
    s = re.sub(r"[\s\-]+", "-", s.strip())
    return s.strip("-")


def _search(host: str, path: str, keyword: str, start: int) -> list[dict]:
    # NOTE: do NOT send an "s" param here. On the MSC tenant it silently
    # switches the query to "browse all" and the keyword is ignored (425 hits
    # of unrelated jobs instead of 23 housekeeping ones).
    params = {"keywords": keyword}
    if start:
        params["from"] = start
    html = common.get_text(f"https://{host}{path}", params=params)
    if not html:
        return []
    m = _DDO.search(html)
    if not m:
        return []
    try:
        ddo = json.loads(m.group(1))
    except Exception:
        return []
    rs = ddo.get("eagerLoadRefineSearch") or ddo.get("refineSearch") or {}
    return (rs.get("data") or {}).get("jobs") or []


def _detail(host: str, job_path: str, job: dict) -> dict:
    jid = job.get("jobId") or job.get("reqId") or ""
    url = f"https://{host}{job_path}/{jid}/{_slug(job.get('title',''))}"
    html = common.get_text(url)
    out = {"apply_url": url, "description_html": "", "date_posted": ""}
    if not html:
        return out
    d = common.extract_jsonld_jobposting(html)
    if not d:
        return out
    out["description_html"] = d.get("description", "")
    out["date_posted"] = d.get("datePosted", "")
    return out


def _is_ship_division(job: dict) -> str | None:
    """Use the board's own division/category text as the shipboard verdict.

    MSC tags every req with AShoreOrOnboard ("Onboard" / "Ashore"), which is
    authoritative — prefer it over any keyword guess. Viking instead uses
    division ("Crew: On our Ships" vs "Shoreside").
    """
    flag = str(job.get("AShoreOrOnboard", "")).strip().lower()
    if flag.startswith("onboard"):
        return "ship"
    if flag.startswith("ashore"):
        return "shore"

    div = " ".join(str(job.get(k, "")) for k in
                   ("division", "cruiseTypeAndLocation", "location", "category"))
    if re.search(r"(on our ships|shipboard|crew|ocean|river|expedition|fleet|vessel)", div, re.I):
        return "ship"
    if re.search(r"(shoreside|corporate|office|head office)", div, re.I):
        return "shore"
    return None


def fetch() -> list[dict]:
    employers, keywords = _cfg()
    records: list[dict] = []

    for emp in employers:
        host, name = emp["host"], emp["name"]
        spath, jpath = emp["search_path"], emp["job_path"]
        seen: dict[str, dict] = {}

        for kw in keywords:
            for page in range(MAX_PAGES):
                jobs = _search(host, spath, kw, page * PAGE)
                if not jobs:
                    break
                for j in jobs:
                    key = str(j.get("jobId") or j.get("reqId") or j.get("jobSeqNo") or "")
                    if key and key not in seen:
                        seen[key] = j
                if len(jobs) < PAGE:
                    break
                time.sleep(SLEEP)
            time.sleep(SLEEP)

        # Only fetch detail pages for jobs that already look like housekeeping —
        # the description is needed for the experience parser, nothing else.
        detailed = 0
        for j in seen.values():
            title = j.get("title", "")
            cat = " ".join(filter(None, [
                str(j.get("category", "")), str(j.get("crewProfessionalFamily", "")),
                str(j.get("department", "")), str(j.get("subCategory", "")),
                " ".join(j.get("multi_category", []) or [])]))
            if not common.classify_housekeeping(title=title, category=cat):
                continue
            det = {"apply_url": f"https://{host}{jpath}/{j.get('jobId','')}/{_slug(title)}",
                   "description_html": "", "date_posted": ""}
            if detailed < MAX_DETAIL:
                det = _detail(host, jpath, j)
                detailed += 1
                time.sleep(SLEEP)
            posting_url = det["apply_url"]

            loc = (j.get("location") or j.get("cityStateCountry")
                   or j.get("cruiseTypeAndLocation") or "")
            if not loc and str(j.get("AShoreOrOnboard", "")).lower().startswith("onboard"):
                loc = "Fleetwide (onboard)"
            rec = common.build_record(
                source="phenom", company=name, brand=emp.get("brand", ""),
                title=title, location=loc,
                department=str(j.get("department", "") or j.get("crewProfessionalFamily", "")),
                division=str(j.get("division", "")),
                category=str(j.get("category", "")),
                apply_url=_apply_url(emp, j, posting_url),
                posting_url=posting_url,
                date_posted=det.get("date_posted") or j.get("postedDate", ""),
                date_created=j.get("dateCreated", ""),
                description_html=det.get("description_html", ""),
                shipboard_hint=_is_ship_division(j),
            )
            if rec:
                records.append(rec)

        print(f"  phenom/{name:16s} {len(seen):4d} unique seen → {detailed} housekeeping detailed")

    print(f"  phenom: {len(records)} records")
    return records


def covered() -> set[tuple[str, str]]:
    employers, _ = _cfg()
    return {("phenom", e["name"]) for e in employers}


if __name__ == "__main__":
    for r in fetch():
        print(f"{r['match_score']:3d} {r['match_verdict']:12s} ship={str(r['shipboard']):5s} "
              f"req={r['req_years_min']} | {r['title'][:45]:45s} | {r['date_posted']}")
