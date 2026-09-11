#!/usr/bin/env python3
"""
scrape_all.py — run every cruise-employer source, record everything as an
evidence trail, then rebuild the curated database of jobs Kasi should apply to.

Usage:
    python scripts/scrape_all.py                    # all sources
    python scripts/scrape_all.py --only phenom      # one source
    python scripts/scrape_all.py --no-detail        # faster, skips detail pages

Each run:
  1. pulls current postings from every source,
  2. writes data/raw/snapshot_<DATE>.jsonl (immutable),
  3. merges into data/processed/jobs_master.{jsonl,csv} (first_seen/last_seen),
  4. closes postings that vanished from a board we actually reached,
  5. rebuilds data/kasi_jobs.db with ONLY postings that are
        shipboard + housekeeping + experience-matched + active + <=30 days old.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ALL_SOURCES = ["workday", "phenom", "radancy", "oraclecloud", "lever",
               "smartrecruiters"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=ALL_SOURCES, help="run only these sources")
    ap.add_argument("--no-detail", action="store_true",
                    help="skip per-job detail pages (faster, weaker experience parsing)")
    args = ap.parse_args()

    sources = args.only or ALL_SOURCES
    print(f"Cruise-ship housekeeping scrape for Kasi — {common.TODAY}")
    print(f"Kasi's housekeeping experience: {common.kasi_housekeeping_years()} years")
    print(f"Freshness window: {common.profile()['freshness']['max_age_days']} days")
    print(f"Sources: {', '.join(sources)}\n")

    all_records: list[dict] = []
    run_counts: dict[str, int] = {}
    covered: set[tuple[str, str]] = set()

    for name in sources:
        print(f"[{name}]")
        try:
            mod = importlib.import_module(f"sources.{name}")
            recs = mod.fetch(**({"want_detail": False} if (args.no_detail and name == "workday") else {}))
            run_counts[name] = len(recs)
            all_records.extend(recs)
            covered |= {(r["source"], r["company"]) for r in recs}
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name} failed: {type(exc).__name__}: {exc}")
            run_counts[name] = 0
        print()

    records = list({r["job_id"]: r for r in all_records}.values())

    snap = common.write_snapshot(records)
    stats = common.merge_into_master(records)
    status = common.update_status(covered)

    master = common.load_master_list()
    out = common.rebuild_db(master, run_counts=run_counts)
    f = out["funnel"]

    with open(os.path.join(common.PROCESSED, "last_run.json"), "w", encoding="utf-8") as fh:
        json.dump({"date": common.TODAY, "run_counts": run_counts,
                   "master": stats["total"], "new": stats["new"],
                   "newly_closed": status["newly_closed"],
                   "kept": out["kept"], "funnel": f,
                   "kasi_years": out["kasi_years"]}, fh, indent=2)

    print("=" * 66)
    print(f"Captured this run   : {len(records)} postings")
    print(f"Snapshot            : {snap}")
    print(f"Master new/updated  : {stats['new']} / {stats['updated']}  (total {stats['total']})")
    print(f"Newly closed        : {status['newly_closed']}   active {status['active']}")
    print()
    print("Filter funnel (against the full master table)")
    print(f"  all postings on record        {f['scraped']:5d}")
    print(f"  → 1. on a ship                {f['shipboard']:5d}")
    print(f"  → 2. housekeeping             {f['housekeeping']:5d}")
    print(f"  → 3. matches Kasi's experience{f['experience']:5d}")
    print(f"  → 4. not turned down by Kasi  {f['wanted']:5d}")
    print(f"  → 5. still active             {f['active']:5d}")
    print(f"  → 6. posted within 30 days    {f['fresh']:5d}")
    print()
    print(f"Curated database    : {out['db']}   ({out['kept']} jobs to apply to)")
    print("=" * 66)

    if out["records"]:
        print("\nTop matches:")
        for r in sorted(out["records"], key=lambda x: -x["match_score"])[:15]:
            print(f"  {r['match_score']:3d}  {r['match_verdict']:12s} "
                  f"{r['company'][:22]:22s} {r['title'][:44]:44s} {r['date_posted']}")


if __name__ == "__main__":
    main()
