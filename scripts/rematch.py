#!/usr/bin/env python3
"""
rematch.py — re-apply the classifiers and the match rules to data already
scraped, without hitting a single website.

Use this after editing profile/kasi_profile.json (his experience grew, he'll
now consider supervisor roles, he wants a 45-day window) or after tuning the
regexes in common.py. It re-derives every classified field from the stored
description and rebuilds the curated database.

    python scripts/rematch.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main() -> None:
    master = common.load_master_list()
    if not master:
        print("No master data yet — run scripts/scrape_all.py first.")
        return

    print(f"Re-matching {len(master)} stored postings "
          f"(Kasi now has {common.kasi_housekeeping_years()} yrs)…")

    for r in master:
        desc = r.get("description", "")
        ship, why = common.classify_shipboard(
            title=r["title"], location=r.get("location", ""),
            department=r.get("department", ""), division=r.get("division", ""),
            description=desc)
        # Never let a re-derived guess overwrite a hint the board itself gave us.
        if r.get("shipboard") is not None and "board declares" in (r.get("shipboard_reason") or ""):
            ship, why = r["shipboard"], r["shipboard_reason"]
        r["shipboard"], r["shipboard_reason"] = ship, why
        r["housekeeping"] = common.classify_housekeeping(
            title=r["title"], department=r.get("department", ""),
            category=r.get("division", ""), description=desc)
        r["role_bucket"] = common.classify_role_bucket(r["title"], r.get("department", ""))
        r["seniority"] = common.classify_seniority(r["title"])
        r["req_years_min"] = common.parse_required_years(desc)
        (r["english_tier"], r["english_certs"],
         r["english_note"]) = common.parse_english_requirement(desc)
        r["match_score"], r["match_verdict"], r["match_reasons"] = common.score_match(
            title=r["title"], description=desc, role_bucket=r["role_bucket"],
            seniority=r["seniority"], req_years=r["req_years_min"])
        r["requirements"] = common.extract_requirements(desc)

    common._write_master({r["job_id"]: r for r in master})
    out = common.rebuild_db(master)
    f = out["funnel"]
    print(f"  on a ship            {f['shipboard']:5d}")
    print(f"  housekeeping         {f['housekeeping']:5d}")
    print(f"  experience match     {f['experience']:5d}")
    print(f"  active               {f['active']:5d}")
    print(f"  fresh                {f['fresh']:5d}")
    print(f"\nCurated DB rebuilt: {out['kept']} jobs → {out['db']}")


if __name__ == "__main__":
    main()
