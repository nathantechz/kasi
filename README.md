# Kasi — cruise ship housekeeping job pipeline

**Live dashboard: https://nathantechz.github.io/kasi/**

A reproducible pipeline that scrapes cruise-line career boards and maintains a
database of **only the jobs Kasi should actually apply to**, plus an interactive
dashboard with a direct apply link for each one.

Built on the same conventions as the sibling `Clinical_trials_R&R` project:
capture broadly into an immutable evidence trail, publish narrowly.

## The six gates

A posting reaches the database only if it passes **all six**:

| # | Gate | Meaning |
|---|------|---------|
| 1 | `shipboard` | The job is worked **on a vessel** — not a shore office, port, or private island |
| 2 | `housekeeping` | It is a housekeeping / cabin / laundry / public-area role |
| 3 | `experience` | The experience the posting **expects** is within reach of what Kasi **has** |
| 4 | `wanted` | It is not a role Kasi has marked *Not interested* |
| 5 | `active` | The posting is still open on the board |
| 6 | `fresh` | Posted **within 30 days** of the pipeline run |

Gate 3 is the interesting one. Kasi's profile lives in
`profile/kasi_profile.json` — B.Sc. Marine Catering & Hotel Management (2024),
Room Attendant at Somerset Greenways since May 2024, valid passport and CDC.
The pipeline parses each job description for its stated minimum experience and
scores the posting against that profile, producing a verdict:

- **`strong_match`** — a core target title at his level, asking for no more experience than he has
- **`stretch`** — a step up (assistant/1st housekeeper) that is still worth an application
- `reach` / `not_a_match` — filtered out, but logged in the `rejected` table with the reason

His years of experience are **computed from the profile at run time**, so the
filter loosens on its own as his tenure grows. No hard-coded numbers.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/run_pipeline.sh
open dashboard/index.html
```

Or step by step:

```bash
.venv/bin/python scripts/scrape_all.py        # scrape → snapshot + master + curated DB
.venv/bin/python scripts/build_dashboard.py   # curated DB → dashboard/index.html
.venv/bin/python scripts/query.py --strong    # terminal view of the best matches
```

## "Not interested" — how Kasi's choices come back

GitHub Pages is static, so the site cannot write to this repo by itself. The
loop is deliberate and explicit:

1. Kasi taps **Not interested** on a job. It disappears from his list
   immediately and the choice is saved in his browser.
2. A **"Roles Kasi turned down"** box appears with a ready-made JSON block.
3. Paste that block into `profile/not_interested.json` under `"exclusions"`
   and commit it.
4. From then on the **pipeline** drops those roles at gate 4, on every machine,
   on every future run.

Exclusions match on **company + normalised title**, not on job id — boards
repost the same role under a new requisition number every few weeks, and keying
on the id would let a rejected role reappear forever.

## English requirements

Every job carries an `english_tier`, so Kasi can see whether a role will cost
him an exam fee and a wait:

| Tier | Meaning |
|------|---------|
| `certificate` | Names a specific test — Marlins, IELTS, TOEFL, CEFR level |
| `fluency` | Wants fluent/proficient English, **no certificate named** |
| `mentioned` | English appears only as a soft communication ask |
| `none` | No English requirement found |

Filter by this on the dashboard. **As of the last run, all 12 matched jobs are
`fluency` and not one requires a certificate** — Kasi does not need to go and
sit an IELTS or Marlins test to apply for any of them.

## What each application asks for

Each job shows a **"What you'll need to fill in"** checklist, captured by
opening the employer's real application form in a browser and enumerating its
fields (the forms are JavaScript-rendered and cannot be read over plain HTTP).
Verified **per employer**, not per job — every posting on one board submits
through an identical form. See `scripts/application_forms.json`; each entry
carries a `verified_on` date and the job it was checked against, and the
`_default` fallback is explicitly marked unverified.

The **Apply** button deep-links straight to the form rather than the job advert,
using the `jobSeqNo` the board already exposes. A separate *Read full posting*
link goes to the advert.

Two things this surfaced that matter:

- **Viking's CV limit is 1MB; MSC's is 3MB.** A CV sized for MSC will be
  rejected by Viking.
- **Viking asks whether you have tattoos visible in uniform.** It is a screening
  question, not an automatic rejection.

## The dashboard

`dashboard/index.html` is a single self-contained file — no server, works
offline, opens on a phone from OneDrive. For every job it shows:

- an **Apply** button that opens the real application page on the employer's board
- the match score and **why** it matched, in plain language
- what the posting asks for vs. what Kasi has (`asks 2+ yrs · Kasi has 2.33`)
- how old the posting is, and whether it is an **evergreen req** the board re-dates daily
- search, filters by verdict / role type / employer, and three sort orders
- a **Mark as applied** tick and a **Not interested** button, saved in the browser
- an **English requirement** filter, and a checklist of what the form will ask for
- a panel of documents to have ready before starting any application

The header shows the funnel — how many postings were on record, and how many
survived each gate — so the number at the top is always traceable.

## Sources

All free, no API keys. Each was probed and verified before being added.

| Source | Platform | Employers | Yield |
|--------|----------|-----------|-------|
| `phenom` | Phenom People (`phApp.ddo`) | MSC Cruises, Viking Ocean / River / Expedition | **the bulk of the matches** |
| `workday` | Workday CXS JSON API | NCL Holdings (NCL, Oceania, Regent, Pride of America), Virgin Voyages | shipboard roles, few housekeeping |
| `radancy` | Radancy TalentBrew | Carnival Corporation | 0 — corporate board only (see below) |
| `smartrecruiters` | SmartRecruiters postings API | expandable token list | 0 so far |

Two honest notes on coverage:

- **Carnival's board is shoreside.** `jobs.carnival.com` responds fine but
  carries only Carnival's Miami corporate reqs (~91). Its shipboard hiring runs
  through approved manning partners and is not on that board, so expect zero
  housekeeping rows from it until a shipboard endpoint is found.
- **Disney is not wired up.** `jobs.disneycareers.com` runs a newer Radancy
  build whose `/search-jobs/results` path does not return JSON. It is parked
  under `_unsupported` in `scripts/employers.json` rather than shipped as a
  source that silently returns nothing.

Add employers by editing `scripts/employers.json`. An unreachable board fails
gracefully and yields zero rows rather than breaking the run. **Probe a host
before adding it** — a config full of hopeful guesses makes runs slow and the
per-source counts meaningless.

## Beyond the job boards — social media leads

A lot of Indian cruise hiring never reaches an ATS. It is advertised on
Instagram by agents and crewing companies. Two facts make that usable:

1. **The vacancies are in the image, not the caption.** A typical post's caption
   is "Vacancies for Indonesians"; the positions are printed on the graphic.
2. **Meta OCRs the graphic for us.** Each post image carries an accessibility
   `alt` attribute with Meta's own transcription, e.g. *"May be a graphic of
   text that says \"VIKING WE'RE HIRING! … -1ST HOUSEKEEPER -ASST CHIEF
   HOUSEKEEPER -STATEROOM STEWARD\""*. No OCR or vision model needed.

The catch: that alt text is injected client-side, so `requests` cannot see it —
a plain fetch returns a 624 KB JavaScript shell with no caption, no
`og:description` and no alt. Capturing it needs a browser, so Instagram is
**snapshot-based**: see `scripts/capture_instagram.md` (a one-minute console
paste). `sources/telegram.py` needs no browser and runs automatically, though
its yield for cruise housekeeping is thin — those channels are mostly cargo and
merchant-navy.

### These are leads, not jobs

Anything from an informal channel goes into a **separate `leads` table** and a
separate dashboard section. It never enters the curated `jobs` table, is never
counted in the funnel, and is never presented as something to apply to.

## Removing scams

Cruise work is one of India's most scammed job markets, so every lead is scored
by `scripts/trust.py` before it is shown.

The hard rule comes from the law: under the Merchant Shipping (Recruitment and
Placement of Seafarers) Rules, a licensed **RPSL** agent may not charge a
seafarer a placement fee. So **any request for money is disqualifying** — it is
either an unlicensed operator or a fraud.

| Band | What happens |
|---|---|
| `high_risk` | **Deleted.** Never rendered, so it cannot be clicked by mistake. Logged in `leads_removed` with reasons, so removal is auditable. |
| `caution` | Shown, badged, with each specific concern listed |
| `looks_ok` | Shown — still unverified, still not a guarantee |

Signals it weighs:

- **Disqualifying** — registration/placement/medical/visa fees, "pay ₹…", UPI/GPay/Western Union
- **Risk** — guaranteed-job claims, "no interview", manufactured urgency, WhatsApp-only contact, free email addresses, demands for passport/CDC before an interview
- **Trust** — an **RPSL licence number** (`RPSL-MUM-219`, checkable at dgshipping.gov.in), a company email domain, a named cruise line, an explicit no-fee pledge

A fee demand **short-circuits everything**. That was a real bug caught by
`selftest.py`: a post quoting a plausible RPSL number and naming a real cruise
line earned enough trust credit to pull a fee demand back down to `caution`.
Since quoting a fake licence beside a real brand is exactly how these scams
launder themselves, a fee demand now rejects outright and says so.

**Where a lead names a cruise line the pipeline already scrapes, the dashboard
says so and points Kasi at the official board** — the right use of a social post
is to learn that a line is hiring, then apply directly rather than through a
middleman.

## Layout

```
Kasi/
├── profile/kasi_profile.json   # Kasi's experience — DRIVES the match filter
├── scripts/
│   ├── common.py               # schema, the five gates, scoring, storage, SQLite
│   ├── employers.json          # which boards to scrape
│   ├── sources/                # one module per platform
│   ├── scrape_all.py           # orchestrator
│   ├── rematch.py              # re-apply rules to stored data, no re-scrape
│   ├── build_dashboard.py      # curated DB → interactive HTML
│   ├── query.py                # terminal queries
│   └── run_pipeline.sh         # scrape + dashboard in one command
├── data/
│   ├── raw/snapshot_<date>.jsonl    # immutable evidence trail
│   ├── processed/jobs_master.{jsonl,csv}   # everything ever seen, first/last_seen
│   └── kasi_jobs.db            # CURATED: only jobs passing all five gates
└── dashboard/index.html
```

## The database

`data/kasi_jobs.db` (SQLite):

- **`jobs`** — the curated set. One row per job Kasi should apply to, with
  `apply_url`, `match_score`, `req_years_min` vs `kasi_years`, `age_days`.
- **`job_reasons`** — why each job matched, one row per reason.
- **`job_requirements`** — the requirement bullets parsed out of the posting.
- **`rejected`** — every *housekeeping* posting that was turned away this run
  and which gate it failed. So "why isn't job X in my dashboard?" is always
  answerable: `python scripts/query.py --rejected`.
- **`runs`** — the funnel counts for each run.

The curated table is **rebuilt** each run, because a job that closed or went
stale must leave it. Nothing is lost: the full history stays in
`data/processed/jobs_master.jsonl` and the dated snapshots in `data/raw/`.

## Tuning it

Edit `profile/kasi_profile.json`, then:

```bash
.venv/bin/python scripts/rematch.py     # re-scores stored data, no network
```

Useful knobs:

- `freshness.max_age_days` — the 30-day window
- `match_rules.max_required_years` — hard ceiling on experience demanded
- `match_rules.grace_years` — how far above his experience is still worth a shot
- `match_rules.keep_verdicts` — set to `["strong_match"]` to be stricter
- `match_rules.target_titles` / `stretch_titles` — the roles he is aiming at

## Checking it still works

```bash
.venv/bin/python scripts/selftest.py
```

Asserts the classifiers against real strings observed on these boards —
including the precision traps that caused actual bugs: MSC files *Tailor*,
*Pool Attendant* and *Floor Runner* under a "Housekeeping & Laundry" category,
*Deck Steward* under Food & Beverage, and *Head Cleaner* under Culinary. None of
those is housekeeping work. Run it after touching any regex in `common.py`.

## Caveats, honestly

- **Evergreen reqs.** MSC and Viking re-date long-running pipeline reqs to
  today. They are flagged `evergreen` in the DB and badged in the dashboard, so
  a "posted today" job that was really opened in 2025 is visible as such rather
  than silently trusted.
- **Boards, not agencies.** Much Indian cruise hiring runs through licensed
  manning agents who publish nothing machine-readable. This pipeline covers the
  cruise lines' own boards; it is not a complete picture of the market.
- **Closure detection** only fires for boards a run actually reached, so a
  source being down never produces false "closed" rows.
