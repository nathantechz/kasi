# AGENTS.md — maintenance contract for the Kasi job pipeline

Conventions mirror the sibling `Clinical_trials_R&R` project.

## Purpose
Maintain a database and dashboard of **open shipboard housekeeping jobs that
match Kasinathan Arumugam's actual experience**, refreshed on demand, with a
working apply link for each and a traceable reason for every inclusion.

## The cardinal rule: capture broadly, publish narrowly
- **Capture everything** a board returns into `data/raw/snapshot_<date>.jsonl`
  and `data/processed/jobs_master.jsonl`. Never delete raw rows.
- **Publish only** what passes all five gates, into `data/kasi_jobs.db`.
- The curated `jobs` table is **rebuilt** every run (stale/closed jobs must
  leave it). History lives in the master + snapshots, never in the curated table.

## The five gates (common.py)
1. `classify_shipboard()` → `shipboard is True`
2. `classify_housekeeping()` → `housekeeping is True`
3. `score_match()` → `match_verdict in profile.match_rules.keep_verdicts`
4. `status == "active"`
5. `is_fresh()` → posted within `profile.freshness.max_age_days`

`gate_report()` evaluates all five for one record; `filter_for_kasi()` applies
them as a cascade and returns the funnel counts. **If you add a gate, add it in
all three places** (the gate dict, the funnel cascade, the dashboard funnel rows)
or the funnel will stop adding up.

## Trust order for classification
Board-provided structure beats keyword guessing. Always, in this order:
1. **A hint the board itself gives.** MSC tags every req `AShoreOrOnboard`;
   Viking uses `division: "Crew: On our Ships"`; a Workday site can be dedicated
   to one vessel (`POA_Careers`) or explicitly shoreside (`NCL_Shoreside_Careers`).
   Adapters pass this as `shipboard_hint=` and it wins outright.
2. **Structured fields** — title, location, department, division.
3. **Free-text description** — last resort only.

`rematch.py` must never overwrite a decision that came from a board hint; it
checks for `"board declares"` in `shipboard_reason` before re-deriving.

## Experience parsing — the fragile part
`parse_required_years()` only trusts a number that sits in a sentence which is
actually about experience (`_EXP_CONTEXT`), and explicitly rejects sentences
about company history, awards, and contract length. This matters: every cruise
JD contains lines like "Viking has more than 450 awards and 100 years of
history". **If you loosen this regex, re-run the assertions in
`scripts/selftest.py` first.**

Kasi's tenure is **computed** by `kasi_housekeeping_years()` from
`profile.match_rules.housekeeping_months_as_of`, never hard-coded, so the filter
loosens by itself over time.

## Adding an employer
Edit `scripts/employers.json` under the right platform key. Set `hint` to
`"ship"` / `"shore"` only when the whole board/site is one or the other;
otherwise leave it `null` and let the classifier decide per posting. Unknown
tokens and dead hosts must fail gracefully and yield zero rows — never raise.

Before adding a host, **probe it**. Don't add a board that has not been observed
returning data; a config full of hopeful guesses makes the run slow and the
source counts meaningless.

## Evergreen requisitions
MSC and Viking re-date long-running pipeline reqs to the current day, so
`date_posted` alone would make everything look fresh. Adapters capture
`dateCreated` as well; `build_record()` sets `evergreen=True` when the gap
exceeds 120 days. Keep surfacing this in the dashboard — hiding it would make
the 30-day gate misleading.

## Auto vs. hand-written
- **AUTO-GENERATED (overwritten every run; do not hand-edit):**
  `data/`, `dashboard/index.html`.
- **HAND-WRITTEN (durable; never overwritten):**
  `README.md`, `AGENTS.md`, `profile/kasi_profile.json`, `scripts/employers.json`.

`profile/kasi_profile.json` is the tuning surface. Prefer changing it over
editing thresholds in `common.py`. After editing it, run `scripts/rematch.py`
(no network) rather than re-scraping.

## Refresh workflow
```bash
./scripts/run_pipeline.sh                     # scrape + rebuild DB + dashboard
.venv/bin/python scripts/rematch.py           # after editing the profile only
.venv/bin/python scripts/query.py --rejected  # why a job isn't in the dashboard
.venv/bin/python scripts/selftest.py          # classifier assertions
```

## Answerability
Every number must trace back to a row. The `rejected` table records each
housekeeping posting that was turned away and the gate it failed, so
"why isn't job X showing?" is always answerable without re-scraping. Do not
drop that table to save space.

## Scope discipline
This pipeline is for **shipboard housekeeping**. Do not widen it to F&B, deck,
galley, or shoreside hotel work without being asked — the value here is that
everything in the dashboard is worth Kasi's time. `_HK_FALSE` in `common.py`
exists to keep galley/dining "steward" roles out; don't remove it.

## The public GitHub Pages site
`https://nathantechz.github.io/kasi/` is served from `main` → `/docs`.
`build_dashboard.py` writes the same HTML to BOTH `dashboard/` (local use) and
`docs/` (what Pages serves). A refresh is therefore: run the pipeline, then
commit `docs/index.html`.

**The repo is PUBLIC.** Before committing anything, check it carries no personal
data. Specifically:
- `*.pdf` is git-ignored — the CV holds his passport number, CDC number, phone,
  email and full date of birth and must never be committed.
- `profile/kasi_profile.json` is deliberately redacted (no DOB, no document
  numbers, first name only). No code path reads those fields; the pipeline only
  uses `match_rules` and `freshness`.
- Match reasons and `application_forms.json` must **not name his current
  employer** — he is job hunting while still employed, and the dashboard is
  public. Say "his serviced-apartment room-attendant experience" instead.

Run this before any push that touches generated output:
```bash
for t in Somerset Kasinathan 7695922163 W4562560 2004; do
  grep -c "$t" docs/index.html; done      # every count must be 0
```

## The "not interested" loop
`profile/not_interested.json` is **hand-written** (via the dashboard's export
box) and is gate 4. Match on `company` + `title_norm`, never on `job_id` —
boards repost the same role under a new requisition id, and an id-keyed
exclusion would silently stop working. `title_contains` is the looser form.

## Application forms
`scripts/application_forms.json` is captured **manually in a browser**, because
these forms are JavaScript-rendered. It is verified per employer, not per job.
Never invent fields: if a form has not been checked, leave the employer out and
let `_default` apply — it is labelled unverified on the dashboard on purpose.
Bump `verified_on` whenever you re-check.

## Informal channels — the rules that matter
`sources/instagram.py` and `sources/telegram.py` produce **leads**, never jobs.
Leads live in their own `leads` table, render in their own dashboard section,
and are excluded from the funnel. **Never merge a lead into `jobs`** — the whole
value of that table is that everything in it came from an employer's own board.

`trust.py` screens every lead. Two invariants:

1. **A fee demand is disqualifying and cannot be offset.** It short-circuits
   before any trust credit is applied. This was a real exploit: quoting an RPSL
   number and a real cruise line pulled a fee-charging post back to `caution`.
   Naming a licence beside a real brand is exactly how these scams look
   official — so treat trust signals as *never* able to rescue a fee demand.
2. **`high_risk` leads are deleted, not greyed out.** A scam still on the page
   is still clickable. They go to `leads_removed` with reasons so the removal is
   auditable rather than silent.

Do not "improve" the scorer by softening these. If you add signals, add
assertions to `selftest.py` in the same commit — the fee-offset bug was caught
only because a test asserted the band directly.

Instagram is snapshot-based on purpose: Meta's alt-text OCR is client-side, so
`requests` cannot read it. Do not write an adapter that pretends to fetch it
live. `scripts/capture_instagram.md` documents the browser step.

## Kasi's documents
`documents/` holds his CV, degree and offer letter and is **git-ignored** — the
repo is public and those carry his address, DOB and identity numbers. Use them
to fill an application accurately. Submitting an application, creating an
account, or entering a password is Kasi's own action, not the agent's.
