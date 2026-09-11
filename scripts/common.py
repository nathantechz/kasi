#!/usr/bin/env python3
"""
common.py — shared schema, classification and longitudinal storage for the
Kasi cruise-ship housekeeping job pipeline.

What this pipeline is for
-------------------------
Kasinathan Arumugam has a B.Sc. in Marine Catering & Hotel Management, ~1.5
years as a Room Attendant in a premium serviced apartment, and a valid
passport + CDC. He wants **shipboard housekeeping** work. So the curated
database deliberately holds ONLY postings that pass every one of these gates:

    1. shipboard      — the job is worked ON a vessel, not in a shore office
    2. housekeeping   — it is a housekeeping / cabin / laundry role
    3. experience fit — the experience the posting expects is within reach of
                        what Kasi actually has (profile/kasi_profile.json)
    4. active         — the posting is still open on the board
    5. fresh          — posted within `max_age_days` of the pipeline run

Everything scraped is kept in data/raw + data/processed as an evidence trail;
the SQLite DB is the *curated* output. That split mirrors the sibling
Clinical_trials_R&R project ("capture broadly, publish narrowly").

Unified record schema (one dict per posting)
--------------------------------------------
    job_id           stable hash of source + company + title + location
    source           workday | phenom | radancy | greenhouse | smartrecruiters
    company          cruise line / employer
    brand            sub-brand or ship where the source exposes one
    title            raw job title as posted
    title_norm       lowercased, punctuation-stripped title (for grouping)
    role_bucket      cabin_steward | public_area | laundry | utility | supervisor | other
    department       department / category as the board reports it
    division         division text (Phenom "Crew: On our Ships" etc.)
    shipboard        True / False / None  — worked on a vessel?
    shipboard_reason why the classifier decided that (audit trail)
    housekeeping     True / False
    location         free-text location
    country          derived country, "" when the board says only "Fleetwide"
    req_years_min    minimum years of experience the posting asks for (None = unstated)
    seniority        entry | attendant | assistant | supervisor | manager | chief | director
    match_score      0-100 fit against Kasi's profile
    match_verdict    strong_match | stretch | reach | not_a_match
    match_reasons    list[str] explaining the score (shown in the dashboard)
    date_posted      ISO date the board says it was published
    date_created     ISO date the req was first created (Phenom exposes this;
                     lets us flag evergreen reqs that get re-dated daily)
    evergreen        True when date_created is far older than date_posted
    date_scraped     ISO date this row was captured
    first_seen/last_seen   longitudinal tracking across runs
    status           active | closed
    apply_url        the link Kasi actually clicks to apply
    description      plain-text job description
    requirements     list[str] of parsed requirement bullets
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import html as _html
import json
import os
import re
import sqlite3
import time
from typing import Iterable

import requests

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
PROCESSED = os.path.join(DATA, "processed")
LOGS = os.path.join(DATA, "logs")
PROFILE = os.path.join(ROOT, "profile", "kasi_profile.json")
EXCLUSIONS = os.path.join(ROOT, "profile", "not_interested.json")
APP_FORMS = os.path.join(HERE, "application_forms.json")
EMPLOYERS = os.path.join(HERE, "employers.json")
MASTER_JSONL = os.path.join(PROCESSED, "jobs_master.jsonl")
MASTER_CSV = os.path.join(PROCESSED, "jobs_master.csv")
DB_PATH = os.path.join(DATA, "kasi_jobs.db")

for _d in (RAW, PROCESSED, LOGS):
    os.makedirs(_d, exist_ok=True)

TODAY = _dt.date.today().isoformat()

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

FIELDNAMES = [
    "job_id", "source", "company", "brand", "title", "title_norm", "role_bucket",
    "department", "division", "shipboard", "shipboard_reason", "housekeeping",
    "location", "country", "req_years_min", "english_tier", "english_certs",
    "english_note", "seniority", "match_score",
    "match_verdict", "match_reasons", "date_posted", "date_created", "evergreen",
    "date_scraped", "first_seen", "last_seen", "status", "closed_date",
    "apply_url", "posting_url", "requirements", "description",
]


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
_PROFILE_CACHE: dict | None = None


def profile() -> dict:
    """Load (and memoise) Kasi's candidate profile."""
    global _PROFILE_CACHE
    if _PROFILE_CACHE is None:
        with open(PROFILE, encoding="utf-8") as fh:
            _PROFILE_CACHE = json.load(fh)
    return _PROFILE_CACHE


def kasi_housekeeping_years(as_of: str | None = None) -> float:
    """Years of housekeeping experience Kasi has as of `as_of` (default: today).

    Computed from the profile rather than hard-coded, so the match filter keeps
    getting more generous on its own as his tenure grows."""
    p = profile()
    start = p["match_rules"]["housekeeping_months_as_of"]
    y0, m0 = (int(x) for x in start.split("-")[:2])
    ref = _dt.date.fromisoformat(as_of) if as_of else _dt.date.today()
    months = (ref.year - y0) * 12 + (ref.month - m0)
    return round(max(months, 0) / 12.0, 2)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: int = 30, retries: int = 2) -> dict | list | None:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
    return None


def post_json(url: str, payload: dict, *, headers: dict | None = None,
              timeout: int = 30, retries: int = 2) -> dict | None:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json",
         "Content-Type": "application/json"}
    h.update(headers or {})
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
    return None


def get_text(url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: int = 30) -> str:
    h = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    h.update(headers or {})
    try:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def strip_html(raw: str | None) -> str:
    """HTML → readable plain text, preserving bullet/line structure."""
    if not raw:
        return ""
    s = raw
    # Some boards double-encode (&lt;p&gt;) — unescape until stable.
    for _ in range(3):
        new = _html.unescape(s)
        if new == s:
            break
        s = new
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "\n• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = s.replace("\xa0", " ").replace("​", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Gate 1 — is this job worked ON A SHIP?
# --------------------------------------------------------------------------- #
# Positive evidence: the board itself says shipboard/fleet/vessel, or the
# location is a ship/brand rather than a city.
_SHIP_POS = re.compile(
    r"(shipboard|ship board|on board|onboard|on our ships|aboard|"
    r"\bvessel\b|\bfleet\b|fleetwide|fleet[- ]wide|"
    r"cruise ship|at sea|seagoing|sea going|sailing|voyage|"
    r"\bcrew\b|shipboard employment|marine crew|"
    r"\bMS\s+[A-Z]|\bMV\s+[A-Z]|\bMSC\s+(Seaside|Meraviglia|World|Grandiosa|Virtuosa|Bellissima|Divina|Fantasia|Preziosa|Splendida|Magnifica|Opera|Lirica|Armonia|Sinfonia|Musica|Poesia|Orchestra|Euribia|Seashore|Seascape|Seaview)|"
    r"river (ship|cruise|vessel)|ocean (&|and) expedition|expedition ship)",
    re.IGNORECASE,
)

# Negative evidence: unambiguous shore roles.
_SHORE_NEG = re.compile(
    r"(shoreside|shore side|shore[- ]based|corporate office|head office|"
    r"headquarters|\bHQ\b|remote work|work from home|\bhybrid\b|"
    r"call cent(er|re)|contact cent(er|re)|reservations cent(er|re)|"
    r"port agent|shore excursion office|warehouse|distribution cent(er|re)|"
    r"private island|shore operations)",
    re.IGNORECASE,
)

# Cities that mark a corporate campus rather than a ship.
_SHORE_CITY = re.compile(
    r"(miami|doral|plantation|seattle|santa clarita|los angeles|london|southampton|"
    r"hamburg|genoa|geneva|naples|monaco|basel|zurich|sunrise, ?fl|weston, ?fl|"
    r"fort lauderdale|new york|toronto|sydney|singapore office|mumbai office)",
    re.IGNORECASE,
)


def classify_shipboard(*, title: str, location: str = "", department: str = "",
                       division: str = "", description: str = "",
                       source_hint: str | None = None) -> tuple[bool | None, str]:
    """Return (is_shipboard, reason).

    `source_hint` lets an adapter assert what the board itself already told us
    (e.g. Phenom's division "Crew: On our Ships", or a Workday site dedicated to
    a single vessel) — that beats any keyword guess.
    """
    if source_hint == "ship":
        return True, "board declares a shipboard/crew division"
    if source_hint == "shore":
        return False, "board declares a shoreside division"

    blob_struct = " ".join([title, location, department, division])
    # Structured fields are far more trustworthy than free-text description.
    if _SHIP_POS.search(blob_struct):
        m = _SHIP_POS.search(blob_struct)
        return True, f"shipboard term in title/location/department: '{m.group(0)}'"
    if _SHORE_NEG.search(blob_struct):
        m = _SHORE_NEG.search(blob_struct)
        return False, f"shoreside term in title/location/department: '{m.group(0)}'"
    if _SHORE_CITY.search(location):
        m = _SHORE_CITY.search(location)
        return False, f"location is a corporate hub: '{m.group(0)}'"

    if _SHIP_POS.search(description or ""):
        m = _SHIP_POS.search(description)
        return True, f"shipboard term in description: '{m.group(0)}'"
    if _SHORE_NEG.search(description or ""):
        m = _SHORE_NEG.search(description)
        return False, f"shoreside term in description: '{m.group(0)}'"
    return None, "no shipboard/shoreside signal found"


# --------------------------------------------------------------------------- #
# Gate 2 — is this a HOUSEKEEPING job?
# --------------------------------------------------------------------------- #
_HK = re.compile(
    r"(housekeep|house keeping|"
    r"(stateroom|cabin|room|accommodation|suite)\s*(steward|attendant|service|clean)|"
    r"steward(ess)?\b|"
    r"public area (attendant|clean)|public areas|"
    r"laundry|linen|launderer|washer|presser|"
    r"utility (clean|hotel|steward)|crew clean|night clean|cleaner\b|cleaning\b|"
    r"turndown|chambermaid|room maid|\bmaid\b|"
    r"butler|sanitation attendant)",
    re.IGNORECASE,
)

# Titles that contain a housekeeping-ish word but are a different job entirely.
# Cruise lines file a lot under a "Housekeeping & Laundry" department umbrella —
# tailors, pool attendants and floor runners among them — so these are excluded
# by title even when the board's own category says housekeeping.
_HK_FALSE = re.compile(
    r"(galley steward|dining\s*(room\s*)?steward|restaurant steward|bar steward|wine steward|"
    r"lounge steward|lounge butler|bar butler|"
    r"\bmess\b|utility galley|dishwash|pot wash|"
    r"chief steward\b|food (and|&) beverage|\bF&B\b|"
    r"\btailor\b|seamstress|upholster|"
    r"pool attendant|beach attendant|locker attendant|floor runner|"
    r"deck (hand|cleaner)|engine|technical clean|hull|tank clean|"
    r"environmental officer|waste (water|management) (engineer|officer))",
    re.IGNORECASE,
)


def classify_housekeeping(*, title: str, department: str = "", category: str = "",
                          description: str = "") -> bool:
    """Housekeeping decided from the TITLE — never from description, and never
    from the board's department/category alone.

    The department is not enough on its own: MSC files Tailor, Pool Attendant
    and Floor Runner under "Housekeeping & Laundry", and none of those is a job
    Kasi is training for. So the title has to carry the evidence, and the
    department is only used to *corroborate* an otherwise-ambiguous title.
    """
    t = title or ""
    dept_blob = f"{department} {category}"
    # The board's own department is a VETO, not just corroboration. MSC files
    # "Deck Steward" under Food & Beverage (pool-deck service) and "Head Cleaner"
    # under Culinary (galley cleaning) — both match a housekeeping word in the
    # title but are somebody else's job.
    vetoed = (_DEPT_VETO.search(dept_blob) and not _DEPT_HK.search(dept_blob))

    if _HK_FALSE.search(t):
        return False
    if _HK.search(t):
        return not vetoed
    # Ambiguous bare titles ("Attendant", "Steward") only count when the board
    # also files them under housekeeping.
    if re.fullmatch(r"\s*(senior |sr\.? |junior |jr\.? |asst\.? |assistant )?"
                    r"(attendant|steward(ess)?|cleaner|utility)\s*", t, re.I):
        return bool(_DEPT_HK.search(dept_blob)) and not vetoed
    return False


# Departments/divisions that mean "this belongs to another team".
_DEPT_VETO = re.compile(
    r"(food (and|&) beverage|\bF&B\b|culinary|galley|restaurant|bar\b|beverage|"
    r"deck\b|engine|technical|marine operations|entertainment|casino|spa\b|"
    r"retail|shore excursion|medical|security|photo|youth)", re.IGNORECASE)

# ...unless the same department text also names housekeeping, which happens on
# boards that use a combined label like "Food & Beverage + Hotel".
_DEPT_HK = re.compile(
    r"(housekeep|laundry|linen|cabin|stateroom|accommodation|public area)",
    re.IGNORECASE)


ROLE_BUCKETS = [
    ("cabin_steward", re.compile(r"(stateroom|cabin|room)\s*(steward|attendant)|"
                                 r"steward(ess)?\b|chambermaid|room maid|butler", re.I)),
    ("laundry",       re.compile(r"laundry|linen|launderer|washer|presser", re.I)),
    ("public_area",   re.compile(r"public area|public space|lobby|night clean", re.I)),
    ("utility",       re.compile(r"utility|crew clean|cleaner\b|cleaning\b|sanitation", re.I)),
    ("supervisor",    re.compile(r"supervisor|manager|chief|director|head\b|"
                                 r"1st housekeeper|first housekeeper|second housekeeper|"
                                 r"assistant housekeep", re.I)),
]


def classify_role_bucket(title: str, department: str = "") -> str:
    blob = f"{title} {department}"
    # Supervisor wins: "Assistant Housekeeping Manager" is a manager, not a steward.
    for name, pat in reversed(ROLE_BUCKETS):
        if name == "supervisor" and pat.search(blob):
            return "supervisor"
    for name, pat in ROLE_BUCKETS:
        if pat.search(blob):
            return name
    return "other"


# --------------------------------------------------------------------------- #
# Gate 3 — does the EXPECTED EXPERIENCE match what Kasi has?
# --------------------------------------------------------------------------- #
_SENIORITY = [
    ("director",   re.compile(r"\b(director|vp|vice president|executive)\b", re.I)),
    ("chief",      re.compile(r"\b(chief|head of|hotel director)\b", re.I)),
    ("manager",    re.compile(r"\b(manager|mgr)\b", re.I)),
    ("supervisor", re.compile(r"\b(supervisor|team leader|leading|foreman|"
                              r"1st housekeeper|first housekeeper)\b", re.I)),
    ("assistant",  re.compile(r"\b(assistant|asst\.?|second|2nd|junior|jr\.?|trainee|apprentice)\b", re.I)),
]

# "minimum 2 years", "2+ years", "at least two years", "1-3 years", "2 to 3 years"
_YEARS_NUM = re.compile(
    r"(?:(?:minimum|min\.?|at least|least|over|more than)\s*(?:of\s*)?)?"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*"
    r"(?:\+|plus)?\s*(?:year|yr)s?\b",
    re.IGNORECASE,
)
_YEARS_WORD = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:\(\d+\)\s*)?(?:year|yr)s?\b",
    re.IGNORECASE,
)
_WORD2NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# Only look for a years figure near experience language — otherwise "2 years
# contract" or "over 100 years of history" poisons the parse.
_EXP_CONTEXT = re.compile(
    r"(experience|background|worked|working|service|tenure|seagoing|sailing|"
    r"in a similar|in similar|related (role|position|field))", re.IGNORECASE)

_ENTRY_HINT = re.compile(
    r"(no (prior |previous )?experience (is )?(required|necessary|needed)|"
    r"entry.?level|no experience|trainee|will train|training provided|"
    r"freshers?|first.?time|newcomers welcome)", re.IGNORECASE)


def parse_required_years(description: str) -> float | None:
    """Smallest experience requirement stated in the JD, in years. None = unstated.

    We scan sentence by sentence and only trust a number that sits in a sentence
    which is actually talking about experience.
    """
    if not description:
        return None
    if _ENTRY_HINT.search(description):
        return 0.0

    found: list[float] = []
    for sentence in re.split(r"[.\n;•]", description):
        if not _EXP_CONTEXT.search(sentence):
            continue
        if re.search(r"\b(company|founded|established|history|since \d{4}|"
                     r"awards|anniversary|contract length|contract of)\b", sentence, re.I):
            continue
        for m in _YEARS_NUM.finditer(sentence):
            lo = int(m.group(1))
            if 0 <= lo <= 15:
                found.append(float(lo))
        for m in _YEARS_WORD.finditer(sentence):
            found.append(float(_WORD2NUM[m.group(1).lower()]))
        # "6 months experience" → 0.5 years
        for m in re.finditer(r"(\d{1,2})\s*months?\b", sentence, re.I):
            months = int(m.group(1))
            if 1 <= months <= 24:
                found.append(round(months / 12.0, 2))
    return min(found) if found else None


# --------------------------------------------------------------------------- #
# English requirement
# --------------------------------------------------------------------------- #
# Cruise lines vary: some merely want "fluent English", others require a named
# certificate (Marlins is the industry-standard shipboard English test; RCL and
# Carnival brands commonly ask for it). Kasi is fluent but holds no certificate,
# so the distinction decides whether a role costs him a test fee and a wait.
_ENG_CERT = re.compile(
    r"(marlins|\bIELTS\b|\bTOEFL\b|\bTOEIC\b|\bCEFR\b|"
    r"\b[ABC][12]\s*(level|proficiency)?\b(?=[^.]{0,40}english)|"
    r"english\s+(?:language\s+)?(?:proficiency\s+)?(?:test|exam|certificat|assessment)|"
    r"(?:certificat\w+|test|exam)\s+(?:of|in)\s+english|"
    r"proof of english)",
    re.IGNORECASE)

# Allow filler between the adjective and "English" — real postings say
# "Fluent in written and spoken English", not "fluent English".
_ENG_FLUENT = re.compile(
    r"("
    r"fluen\w*[^.]{0,40}?\benglish\b|\benglish\b[^.]{0,20}?fluen\w*|"
    r"proficien\w*[^.]{0,40}?\benglish\b|\benglish\b[^.]{0,20}?proficien\w*|"
    r"(?:excellent|strong|solid|advanced|good|intermediate)[^.]{0,40}?\benglish\b|"
    r"\benglish\b[^.]{0,30}?(?:is\s+)?(?:required|mandatory|essential)|"
    r"must speak english|command of english"
    r")",
    re.IGNORECASE)

_ENG_ANY = re.compile(r"\benglish\b", re.IGNORECASE)


def parse_english_requirement(description: str) -> tuple[str, list[str], str]:
    """Grade a posting's English requirement.

    Returns (tier, certificates, evidence sentence) where tier is one of:
        certificate — names a specific test/certificate (Marlins, IELTS, CEFR...)
        fluency     — demands fluent/proficient English, no certificate named
        mentioned   — English appears, but only as a soft communication ask
        none        — no English requirement found

    Only `certificate` means Kasi would need to go and sit an exam.
    """
    if not description:
        return "none", [], ""

    sentences = [re.sub(r"\s+", " ", x).strip()
                 for x in re.split(r"[.\n•;]", description)]
    sentences = [x for x in sentences if _ENG_ANY.search(x) or _ENG_CERT.search(x)]

    certs: list[str] = []
    evidence = ""
    for sent in sentences:
        for m in _ENG_CERT.finditer(sent):
            token = m.group(0).strip()
            # ignore "proficiency in computers/PC/Excel" style false hits
            if re.search(r"proficien\w*\s+(?:with|in)\s+(?!english)"
                         r"(pc|computer|ms |microsoft|excel|word|database|spread)",
                         sent, re.I) and not re.search(r"english", token, re.I):
                continue
            certs.append(token)
            if not evidence:
                evidence = sent[:220]
    if certs:
        seen, uniq = set(), []
        for c in certs:
            k = c.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(c)
        return "certificate", uniq, evidence

    for sent in sentences:
        if _ENG_FLUENT.search(sent):
            return "fluency", [], sent[:220]
    if sentences:
        return "mentioned", [], sentences[0][:220]
    return "none", [], ""


def classify_seniority(title: str) -> str:
    for name, pat in _SENIORITY:
        if pat.search(title):
            return name
    if re.search(r"(attendant|steward|cleaner|maid|utility|crew clean)", title, re.I):
        return "attendant"
    return "entry"


def score_match(*, title: str, description: str, role_bucket: str,
                seniority: str, req_years: float | None,
                as_of: str | None = None) -> tuple[int, str, list[str]]:
    """Score this posting against Kasi's profile → (0-100, verdict, reasons)."""
    p = profile()
    rules = p["match_rules"]
    have = kasi_housekeeping_years(as_of)
    tl = normalize_title(title)
    reasons: list[str] = []
    score = 50

    # --- title alignment -------------------------------------------------- #
    if any(t in tl for t in rules["target_titles"]):
        score += 28
        reasons.append(f"title is a core target role for Kasi ({have} yrs room attendant)")
    elif any(t in tl for t in rules["stretch_titles"]):
        score += 6
        reasons.append("title is a step up from Kasi's current level — a stretch")
    elif role_bucket in ("cabin_steward", "public_area", "laundry", "utility"):
        score += 18
        reasons.append(f"housekeeping role of type '{role_bucket}'")

    # --- seniority --------------------------------------------------------- #
    if seniority in rules["rejected_seniority"]:
        score -= 45
        reasons.append(f"seniority '{seniority}' is above Kasi's experience level")
    elif seniority in rules["allowed_seniority"]:
        score += 12
        reasons.append(f"seniority '{seniority}' fits an entry-level applicant")

    # --- required experience vs. what he actually has ---------------------- #
    grace = float(rules["grace_years"])
    if req_years is None:
        reasons.append("posting does not state a years-of-experience requirement")
    elif req_years <= have:
        score += 22
        reasons.append(f"asks for {req_years:g} yrs — Kasi has {have:g} yrs")
    elif req_years <= have + grace:
        score += 8
        reasons.append(f"asks for {req_years:g} yrs vs Kasi's {have:g} — within reach")
    elif req_years > float(rules["max_required_years"]):
        score -= 45
        reasons.append(f"asks for {req_years:g} yrs — well beyond Kasi's {have:g}")
    else:
        score -= 18
        reasons.append(f"asks for {req_years:g} yrs — above Kasi's {have:g}")

    # --- transferable credentials ------------------------------------------ #
    d = description or ""
    if re.search(r"(hotel|resort|hospitality|serviced apartment|5.?star|four.?star)", d, re.I):
        score += 6
        # Deliberately does NOT name his current employer: the dashboard is
        # published publicly and he is job hunting while still employed.
        reasons.append("wants hotel/hospitality background — matches his "
                       "serviced-apartment room-attendant experience")
    if re.search(r"\b(CDC|seaman.?s book|seafarer|STCW|marine document)\b", d, re.I):
        score += 5
        reasons.append("wants seafarer documents — Kasi holds a valid CDC")
    if re.search(r"(english)", d, re.I):
        score += 3
        reasons.append("English requirement — Kasi is fluent")
    if re.search(r"\b(degree|diploma|b\.?sc|hotel management|catering)\b", d, re.I):
        score += 4
        reasons.append("hospitality qualification valued — B.Sc. Marine Catering & Hotel Mgmt")

    score = max(0, min(100, score))
    if score >= 75:
        verdict = "strong_match"
    elif score >= 58:
        verdict = "stretch"
    elif score >= 40:
        verdict = "reach"
    else:
        verdict = "not_a_match"
    return score, verdict, reasons


# --------------------------------------------------------------------------- #
# Gate 5 — freshness
# --------------------------------------------------------------------------- #
def parse_date(value: str | None) -> str:
    """Normalise assorted board date formats to ISO YYYY-MM-DD ('' if unknown)."""
    if not value:
        return ""
    s = str(value).strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    # Workday's relative strings: "Posted 6 Days Ago", "Posted Today"
    low = s.lower()
    today = _dt.date.today()
    if "today" in low:
        return today.isoformat()
    if "yesterday" in low:
        return (today - _dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days?\s*ago", low)
    if m:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\+?\s*months?\s*ago", low)
    if m:
        return (today - _dt.timedelta(days=30 * int(m.group(1)))).isoformat()
    return ""


def age_days(date_posted: str, ref: str | None = None) -> int | None:
    if not date_posted:
        return None
    try:
        d = _dt.date.fromisoformat(date_posted)
    except ValueError:
        return None
    r = _dt.date.fromisoformat(ref) if ref else _dt.date.today()
    return (r - d).days


def is_fresh(date_posted: str, ref: str | None = None) -> bool:
    """Within the profile's max_age_days of the run date.

    A posting with NO date is treated as not fresh — we only publish postings we
    can prove are recent, rather than guessing."""
    limit = int(profile()["freshness"]["max_age_days"])
    a = age_days(date_posted, ref)
    return a is not None and 0 <= a <= limit


# --------------------------------------------------------------------------- #
# Record construction
# --------------------------------------------------------------------------- #
def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9/&\s-]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def make_job_id(source: str, company: str, title: str, location: str) -> str:
    key = f"{source}|{company}|{normalize_title(title)}|{(location or '').lower().strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


_COUNTRY_HINTS = [
    ("India", re.compile(r"\b(india|chennai|mumbai|delhi|kochi|goa|kolkata|bengaluru)\b", re.I)),
    ("USA", re.compile(r"\b(usa|united states|florida|miami|seattle|california|"
                       r"hawaii|alaska|new york|texas|\bFL\b|\bWA\b|\bCA\b)\b", re.I)),
    ("UK", re.compile(r"\b(united kingdom|england|london|southampton|scotland|\bUK\b)\b", re.I)),
    ("Italy", re.compile(r"\b(italy|genoa|naples|venice|sorrento)\b", re.I)),
    ("Germany", re.compile(r"\b(germany|hamburg|rostock|berlin)\b", re.I)),
    ("Switzerland", re.compile(r"\b(switzerland|geneva|basel|zurich)\b", re.I)),
    ("Netherlands", re.compile(r"\b(netherlands|amsterdam|rotterdam)\b", re.I)),
    ("Norway", re.compile(r"\b(norway|oslo|bergen|tromso)\b", re.I)),
    ("Philippines", re.compile(r"\b(philippines|manila|cebu)\b", re.I)),
    ("Belize", re.compile(r"\bbelize\b", re.I)),
    ("Bahamas", re.compile(r"\b(bahamas|nassau)\b", re.I)),
]


def extract_country(location: str) -> str:
    loc = location or ""
    if re.search(r"(fleet|shipboard|onboard|on board|at sea|vessel|global|worldwide|"
                 r"various|multiple|ocean|river|expedition)", loc, re.I):
        return ""      # a ship has no country — leave blank rather than invent one
    for name, pat in _COUNTRY_HINTS:
        if pat.search(loc):
            return name
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    return parts[-1] if len(parts) > 1 else ""


# Match ld+json script tags with ANY attributes — several boards add a CSP
# `nonce` and an `id`, which a stricter `<script type="application/ld+json">`
# pattern silently misses (costing us every description on that board).
_LD_BLOCK = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def extract_jsonld_jobposting(html_text: str) -> dict:
    """Return the schema.org JobPosting object from a job page, or {}.

    A page usually carries several ld+json blocks (WebPage, BreadcrumbList,
    FAQPage, JobPosting) — pick the JobPosting rather than the first one.
    """
    for block in _LD_BLOCK.findall(html_text or ""):
        try:
            d = json.loads(block.strip())
        except Exception:
            continue
        cands = d if isinstance(d, list) else [d]
        for c in cands:
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                return c
    return {}


def jsonld_location(d: dict) -> str:
    loc = d.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address", {}) or {}
    return ", ".join(filter(None, [addr.get("addressLocality", ""),
                                   addr.get("addressRegion", ""),
                                   addr.get("addressCountry", "")]))


_REQ_HEADER = re.compile(
    r"^\s*(requirement|qualification|what you (bring|need|will need)|"
    r"skills|experience|we('| a)re looking for|your profile|about you|"
    r"minimum|essential|desired|preferred)", re.IGNORECASE)


def extract_requirements(plain: str) -> list[str]:
    """Pull the bullets under a requirements-ish heading (capped)."""
    if not plain:
        return []
    out: list[str] = []
    capturing = False
    for line in plain.splitlines():
        s = line.strip()
        if not s:
            continue
        if _REQ_HEADER.match(s.rstrip(":")) and len(s) < 90:
            capturing = True
            continue
        if capturing:
            if re.match(r"^[A-Z][A-Za-z /&]{3,40}:?$", s) and not s.startswith("•"):
                # a new section heading ends the requirements block
                if not _REQ_HEADER.match(s.rstrip(":")):
                    capturing = False
                    continue
            cleaned = s.lstrip("•-–*● ").strip()
            if 8 <= len(cleaned) <= 400:
                out.append(cleaned)
        if len(out) >= 25:
            break
    return out


def build_record(*, source: str, company: str, title: str, apply_url: str,
                 location: str = "", brand: str = "", department: str = "",
                 division: str = "", category: str = "",
                 date_posted: str = "", date_created: str = "",
                 description_html: str = "", description_text: str = "",
                 posting_url: str = "",
                 shipboard_hint: str | None = None) -> dict | None:
    """Build one unified record. Returns None only for junk (no title/url).

    NOTE: this does NOT apply the gates — every scraped posting is recorded so
    the raw snapshot stays a complete evidence trail. `filter_for_kasi()` and
    the DB layer decide what is actually published.
    """
    title = (title or "").strip()
    if not title or not apply_url:
        return None

    desc = description_text or strip_html(description_html)
    ship, ship_why = classify_shipboard(
        title=title, location=location, department=department,
        division=division or category, description=desc, source_hint=shipboard_hint)
    hk = classify_housekeeping(title=title, department=department,
                               category=category or division, description=desc)
    bucket = classify_role_bucket(title, department or category)
    seniority = classify_seniority(title)
    req_years = parse_required_years(desc)
    eng_tier, eng_certs, eng_note = parse_english_requirement(desc)
    score, verdict, reasons = score_match(
        title=title, description=desc, role_bucket=bucket,
        seniority=seniority, req_years=req_years)

    dp = parse_date(date_posted)
    dc = parse_date(date_created)
    evergreen = False
    if dp and dc:
        try:
            evergreen = (_dt.date.fromisoformat(dp) - _dt.date.fromisoformat(dc)).days > 120
        except ValueError:
            evergreen = False

    return {
        "job_id": make_job_id(source, company, title, location),
        "source": source,
        "company": company,
        "brand": brand,
        "title": title,
        "title_norm": normalize_title(title),
        "role_bucket": bucket,
        "department": department,
        "division": division or category,
        "shipboard": ship,
        "shipboard_reason": ship_why,
        "housekeeping": hk,
        "location": location,
        "country": extract_country(location),
        "req_years_min": req_years,
        "english_tier": eng_tier,
        "english_certs": eng_certs,
        "english_note": eng_note,
        "seniority": seniority,
        "match_score": score,
        "match_verdict": verdict,
        "match_reasons": reasons,
        "date_posted": dp,
        "date_created": dc,
        "evergreen": evergreen,
        "date_scraped": TODAY,
        "first_seen": TODAY,
        "last_seen": TODAY,
        "status": "active",
        "closed_date": "",
        "apply_url": apply_url,
        "posting_url": posting_url or apply_url,
        "apply_form": application_form_for(company),
        "requirements": extract_requirements(desc),
        "description": desc[:20000],
    }


# --------------------------------------------------------------------------- #
# What the employer's application form asks for
# --------------------------------------------------------------------------- #
_FORMS_CACHE: dict | None = None


def application_forms() -> dict:
    global _FORMS_CACHE
    if _FORMS_CACHE is None:
        try:
            with open(APP_FORMS, encoding="utf-8") as fh:
                _FORMS_CACHE = json.load(fh)
        except Exception:
            _FORMS_CACHE = {"forms": {}, "_always_have_ready": {"items": []}}
    return _FORMS_CACHE


def application_form_for(company: str) -> dict:
    """The application-form spec for an employer, or the generic fallback.

    Verified per employer rather than per job: every posting on one board
    submits through the same form. `_default` is explicitly marked unverified so
    the dashboard never implies we checked a form we did not.
    """
    forms = application_forms().get("forms", {})
    return forms.get(company) or forms.get("_default") or {}


def always_have_ready() -> list[str]:
    return application_forms().get("_always_have_ready", {}).get("items", [])


# --------------------------------------------------------------------------- #
# Gate 6 — roles Kasi has said he is not interested in
# --------------------------------------------------------------------------- #
_EXCL_CACHE: list[dict] | None = None


def exclusions() -> list[dict]:
    """Load Kasi's 'not interested' list (profile/not_interested.json)."""
    global _EXCL_CACHE
    if _EXCL_CACHE is None:
        try:
            with open(EXCLUSIONS, encoding="utf-8") as fh:
                _EXCL_CACHE = json.load(fh).get("exclusions", []) or []
        except Exception:
            _EXCL_CACHE = []
    return _EXCL_CACHE


def is_excluded(rec: dict) -> tuple[bool, str]:
    """Has Kasi turned this role down before?

    Matches on company + normalised TITLE rather than job_id, because boards
    repost the same role under a new requisition id every few weeks — keying on
    the id would let a rejected role reappear forever.
    """
    title_norm = (rec.get("title_norm") or normalize_title(rec.get("title", "")))
    company = (rec.get("company") or "").strip().lower()
    for ex in exclusions():
        ex_company = (ex.get("company") or "").strip().lower()
        if ex_company and ex_company != company:
            continue
        want = (ex.get("title_norm") or "").strip().lower()
        contains = (ex.get("title_contains") or "").strip().lower()
        if want and title_norm == want:
            return True, ex.get("reason", "marked not interested")
        if contains and contains in title_norm:
            return True, ex.get("reason", "marked not interested")
    return False, ""


# --------------------------------------------------------------------------- #
# The gates, applied
# --------------------------------------------------------------------------- #
def gate_report(rec: dict, ref: str | None = None) -> dict:
    """Evaluate every gate for one record and say which ones it failed."""
    keep_verdicts = profile()["match_rules"]["keep_verdicts"]
    excluded, _why = is_excluded(rec)
    gates = {
        "shipboard":  rec.get("shipboard") is True,
        "housekeeping": bool(rec.get("housekeeping")),
        "experience": rec.get("match_verdict") in keep_verdicts,
        "wanted":     not excluded,
        "active":     rec.get("status", "active") == "active",
        "fresh":      is_fresh(rec.get("date_posted", ""), ref),
    }
    return {"passed": all(gates.values()),
            "gates": gates,
            "failed": [k for k, v in gates.items() if not v]}


def filter_for_kasi(records: Iterable[dict], ref: str | None = None) -> tuple[list[dict], dict]:
    """Apply all five gates. Returns (kept, funnel_counts)."""
    kept: list[dict] = []
    funnel = {"scraped": 0, "shipboard": 0, "housekeeping": 0,
              "experience": 0, "wanted": 0, "active": 0, "fresh": 0}
    for r in records:
        funnel["scraped"] += 1
        rep = gate_report(r, ref)
        g = rep["gates"]
        # Report the funnel as a cascade so it reads like a real drop-off.
        if not g["shipboard"]:
            continue
        funnel["shipboard"] += 1
        if not g["housekeeping"]:
            continue
        funnel["housekeeping"] += 1
        if not g["experience"]:
            continue
        funnel["experience"] += 1
        if not g["wanted"]:
            continue
        funnel["wanted"] += 1
        if not g["active"]:
            continue
        funnel["active"] += 1
        if not g["fresh"]:
            continue
        funnel["fresh"] += 1
        kept.append(r)
    return kept, funnel


# --------------------------------------------------------------------------- #
# Longitudinal storage — raw snapshot + master table
# --------------------------------------------------------------------------- #
def _row_for_csv(rec: dict) -> dict:
    row = {}
    for k in FIELDNAMES:
        v = rec.get(k, "")
        if isinstance(v, list):
            v = " | ".join(str(x) for x in v)
        elif isinstance(v, bool) or v is None:
            v = "" if v is None else ("yes" if v else "no")
        row[k] = v
    return row


def write_snapshot(records: list[dict]) -> str:
    path = os.path.join(RAW, f"snapshot_{TODAY}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _load_master() -> dict[str, dict]:
    master: dict[str, dict] = {}
    if os.path.exists(MASTER_JSONL):
        with open(MASTER_JSONL, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    master[r["job_id"]] = r
                except Exception:
                    continue
    return master


def _write_master(master: dict[str, dict]) -> None:
    with open(MASTER_JSONL, "w", encoding="utf-8") as fh:
        for r in master.values():
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(MASTER_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        for r in master.values():
            w.writerow(_row_for_csv(r))


def merge_into_master(records: list[dict]) -> dict:
    """Merge this run into the master, preserving first_seen across runs."""
    master = _load_master()
    new = updated = 0
    touched: set[str] = set()
    for r in records:
        jid = r["job_id"]
        touched.add(jid)
        if jid in master:
            prev = master[jid]
            r["first_seen"] = prev.get("first_seen", r["first_seen"])
            if prev.get("status") == "closed":
                r["closed_date"] = ""      # reappeared → reopened
            r["last_seen"] = TODAY
            r["status"] = "active"
            master[jid] = r
            updated += 1
        else:
            master[jid] = r
            new += 1
    _write_master(master)
    return {"new": new, "updated": updated, "total": len(master), "touched": touched}


def update_status(covered: set[tuple[str, str]]) -> dict:
    """Close postings that didn't reappear on a board we actually reached today.

    `covered` = the (source, company) pairs that returned data this run, so a
    source that was down never causes false 'closed' rows.
    """
    master = _load_master()
    newly_closed = reactivated = 0
    changed: set[str] = set()
    for jid, r in master.items():
        key = (r.get("source"), r.get("company"))
        if key not in covered:
            continue
        if r.get("last_seen") == TODAY:
            if r.get("status") != "active":
                r["status"] = "active"
                r["closed_date"] = ""
                reactivated += 1
                changed.add(jid)
            continue
        if r.get("status") == "active":
            r["status"] = "closed"
            r["closed_date"] = TODAY
            newly_closed += 1
            changed.add(jid)
    _write_master(master)
    active = sum(1 for r in master.values() if r.get("status") == "active")
    return {"newly_closed": newly_closed, "reactivated": reactivated,
            "active": active, "closed": len(master) - active,
            "changed_ids": changed}


def load_master_list() -> list[dict]:
    return list(_load_master().values())


# --------------------------------------------------------------------------- #
# The curated database — ONLY jobs that pass all five gates
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    source           TEXT,
    company          TEXT,
    brand            TEXT,
    title            TEXT,
    title_norm       TEXT,
    role_bucket      TEXT,
    department       TEXT,
    division         TEXT,
    shipboard        INTEGER,
    shipboard_reason TEXT,
    housekeeping     INTEGER,
    location         TEXT,
    country          TEXT,
    req_years_min    REAL,
    english_tier     TEXT,
    english_certs    TEXT,
    english_note     TEXT,
    kasi_years       REAL,
    seniority        TEXT,
    match_score      INTEGER,
    match_verdict    TEXT,
    date_posted      TEXT,
    date_created     TEXT,
    evergreen        INTEGER,
    age_days         INTEGER,
    date_scraped     TEXT,
    first_seen       TEXT,
    last_seen        TEXT,
    status           TEXT,
    apply_url        TEXT,
    posting_url      TEXT,
    description      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_verdict ON jobs(match_verdict);
CREATE INDEX IF NOT EXISTS idx_jobs_bucket  ON jobs(role_bucket);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_posted  ON jobs(date_posted);

CREATE TABLE IF NOT EXISTS job_reasons (
    job_id  TEXT,
    idx     INTEGER,
    reason  TEXT,
    PRIMARY KEY (job_id, idx)
);

CREATE TABLE IF NOT EXISTS job_requirements (
    job_id      TEXT,
    idx         INTEGER,
    requirement TEXT,
    PRIMARY KEY (job_id, idx)
);

CREATE TABLE IF NOT EXISTS runs (
    run_date       TEXT PRIMARY KEY,
    scraped        INTEGER,
    passed_ship    INTEGER,
    passed_hk      INTEGER,
    passed_exp     INTEGER,
    passed_wanted  INTEGER,
    passed_active  INTEGER,
    passed_fresh   INTEGER,
    kept           INTEGER,
    kasi_years     REAL,
    max_age_days   INTEGER,
    source_counts  TEXT
);

CREATE TABLE IF NOT EXISTS rejected (
    run_date    TEXT,
    job_id      TEXT,
    title       TEXT,
    company     TEXT,
    failed_gate TEXT,
    PRIMARY KEY (run_date, job_id)
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def rebuild_db(all_records: list[dict], *, run_counts: dict | None = None,
               ref: str | None = None) -> dict:
    """Rewrite the curated DB from the master table.

    The DB is a *view of what Kasi should look at right now*: jobs that pass all
    five gates. It is rebuilt each run rather than appended, because a posting
    that has gone stale or closed must leave the DB. The full history stays in
    data/processed/jobs_master.jsonl and data/raw/.
    """
    kept, funnel = filter_for_kasi(all_records, ref)
    have = kasi_housekeeping_years(ref)
    max_age = int(profile()["freshness"]["max_age_days"])

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM jobs")
    cur.execute("DELETE FROM job_reasons")
    cur.execute("DELETE FROM job_requirements")
    cur.execute("DELETE FROM rejected WHERE run_date = ?", (TODAY,))

    for r in kept:
        cur.execute("""
            INSERT OR REPLACE INTO jobs (
              job_id, source, company, brand, title, title_norm, role_bucket,
              department, division, shipboard, shipboard_reason, housekeeping,
              location, country, req_years_min, english_tier, english_certs,
              english_note, kasi_years, seniority, match_score,
              match_verdict, date_posted, date_created, evergreen, age_days,
              date_scraped, first_seen, last_seen, status, apply_url, posting_url,
              description
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            r["job_id"], r["source"], r["company"], r["brand"], r["title"],
            r["title_norm"], r["role_bucket"], r["department"], r["division"],
            1 if r["shipboard"] else 0, r["shipboard_reason"],
            1 if r["housekeeping"] else 0, r["location"], r["country"],
            r["req_years_min"], r.get("english_tier", ""),
            ", ".join(r.get("english_certs", []) or []), r.get("english_note", ""),
            have, r["seniority"], r["match_score"],
            r["match_verdict"], r["date_posted"], r["date_created"],
            1 if r["evergreen"] else 0, age_days(r["date_posted"], ref),
            r["date_scraped"], r["first_seen"], r["last_seen"], r["status"],
            r["apply_url"], r.get("posting_url", r["apply_url"]), r["description"]))
        for i, reason in enumerate(r.get("match_reasons", [])):
            cur.execute("INSERT OR REPLACE INTO job_reasons VALUES (?,?,?)",
                        (r["job_id"], i, reason))
        for i, req in enumerate(r.get("requirements", [])):
            cur.execute("INSERT OR REPLACE INTO job_requirements VALUES (?,?,?)",
                        (r["job_id"], i, req))

    # Keep an audit row for every housekeeping posting we turned away, so it is
    # always answerable *why* something Kasi saw online isn't in the dashboard.
    kept_ids = {r["job_id"] for r in kept}
    for r in all_records:
        if r["job_id"] in kept_ids:
            continue
        if not r.get("housekeeping"):
            continue
        rep = gate_report(r, ref)
        cur.execute("INSERT OR REPLACE INTO rejected VALUES (?,?,?,?,?)",
                    (TODAY, r["job_id"], r["title"], r["company"],
                     ",".join(rep["failed"])))

    cur.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
        TODAY, funnel["scraped"], funnel["shipboard"], funnel["housekeeping"],
        funnel["experience"], funnel["wanted"], funnel["active"], funnel["fresh"],
        len(kept), have, max_age, json.dumps(run_counts or {})))

    conn.commit()
    conn.close()
    return {"db": DB_PATH, "kept": len(kept), "funnel": funnel,
            "kasi_years": have, "records": kept}
