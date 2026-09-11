#!/usr/bin/env python3
"""
query.py — quick look at the curated database from the terminal.

    python scripts/query.py                 # every job, best match first
    python scripts/query.py --strong        # strong matches only
    python scripts/query.py --links         # just titles + apply URLs
    python scripts/query.py --why <job_id>  # full reasoning for one job
    python scripts/query.py --rejected      # housekeeping jobs that were filtered out, and why
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strong", action="store_true")
    ap.add_argument("--links", action="store_true")
    ap.add_argument("--why", metavar="JOB_ID")
    ap.add_argument("--rejected", action="store_true")
    args = ap.parse_args()
    conn = common.get_db()

    if args.why:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (args.why,)).fetchone()
        if not row:
            print("No such job in the curated DB.")
            return
        print(f"{row['title']} — {row['company']}  ({row['match_score']}, {row['match_verdict']})")
        print(f"  ship     : {row['shipboard_reason']}")
        print(f"  asks for : {row['req_years_min']} yrs   Kasi has {row['kasi_years']} yrs")
        print(f"  posted   : {row['date_posted']} ({row['age_days']} days ago)")
        print(f"  apply    : {row['apply_url']}\n  reasons:")
        for r in conn.execute("SELECT reason FROM job_reasons WHERE job_id=? ORDER BY idx", (args.why,)):
            print(f"   • {r[0]}")
        return

    if args.rejected:
        rows = conn.execute(
            "SELECT title, company, failed_gate FROM rejected "
            "WHERE run_date=(SELECT MAX(run_date) FROM rejected) ORDER BY failed_gate, company").fetchall()
        print(f"{len(rows)} housekeeping postings filtered out:\n")
        for r in rows:
            print(f"  {r['failed_gate']:28s} {r['company'][:22]:22s} {r['title'][:46]}")
        return

    sql = "SELECT * FROM jobs"
    if args.strong:
        sql += " WHERE match_verdict='strong_match'"
    sql += " ORDER BY match_score DESC, date_posted DESC"
    rows = conn.execute(sql).fetchall()

    if args.links:
        for r in rows:
            print(f"{r['title']} — {r['company']}\n  {r['apply_url']}\n")
        return

    run = conn.execute("SELECT * FROM runs ORDER BY run_date DESC LIMIT 1").fetchone()
    if run:
        print(f"Run {run['run_date']} — {run['kept']} jobs kept from {run['scraped']} on record "
              f"(Kasi: {run['kasi_years']} yrs, window {run['max_age_days']}d)\n")
    for r in rows:
        req = f"{r['req_years_min']}y" if r["req_years_min"] is not None else "—"
        print(f"{r['match_score']:3d} {r['match_verdict']:12s} {r['company'][:20]:20s} "
              f"{r['title'][:42]:42s} asks:{req:>4s} {r['date_posted']} ({r['age_days']}d)")
        print(f"     {r['apply_url']}")
    print(f"\n{len(rows)} jobs.")


if __name__ == "__main__":
    main()
