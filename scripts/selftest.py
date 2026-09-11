#!/usr/bin/env python3
"""
selftest.py — assertions for the classifiers, using real strings observed on
the cruise boards. Run this after touching any regex in common.py.

    python scripts/selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

FAILS: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{label}\n     got  {got!r}\n     want {want!r}")


# --- gate 2: housekeeping ------------------------------------------------- #
for title, cat, want in [
    ("OCEAN - Stateroom Steward/ess", "Housekeeping & Laundry", True),
    ("Crew Cleaner", "Housekeeping & Laundry", True),
    ("Laundry Attendant", "Housekeeping & Laundry", True),
    ("Public Area Attendant", "Housekeeping & Laundry", True),
    ("Linen Keeper", "Housekeeping & Laundry", True),
    ("Cabin Steward", "", True),
    ("Assistant Housekeeping Manager", "Housekeeping", True),
    # these contain a housekeeping-ish word but are different jobs
    ("Galley Steward", "Food & Beverage", False),
    ("Dining Room Steward", "Food & Beverage", False),
    ("Wine Steward", "Food & Beverage", False),
    ("Deckhand", "Deck", False),
    ("Photographer", "", False),
    ("Broadcast Technician", "", False),
    ("Senior Managing Director", "Other", False),
    # filed by MSC under "Housekeeping & Laundry" but NOT housekeeping work:
    ("Tailor", "Housekeeping & Laundry", False),
    ("Pool Attendant", "Housekeeping & Laundry", False),
    ("Floor Runner", "Housekeeping & Laundry", False),
    ("Lounge Butler", "Housekeeping & Laundry", False),
    # genuinely housekeeping despite an unusual title:
    ("Officer Staff Steward", "Housekeeping", True),
    ("Laundry Operator", "Housekeeping & Laundry", True),
    ("Butler", "Housekeeping", True),
]:
    check(f"housekeeping({title!r})",
          common.classify_housekeeping(title=title, category=cat), want)

# The board's department VETOES a title match when the job belongs to another
# team — both of these were real false positives from the MSC board.
check("housekeeping(Deck Steward / F&B division)",
      common.classify_housekeeping(title="Deck Steward",
                                   department="Food & Beverage + Hotel",
                                   category="Food & Beverage"), False)
check("housekeeping(Head Cleaner / Culinary division)",
      common.classify_housekeeping(title="Head Cleaner",
                                   department="Food & Beverage + Hotel",
                                   category="Culinary"), False)
# ...but a combined "F&B + Hotel" label that also says Housekeeping must NOT veto:
check("housekeeping(Linen Keeper / F&B+Hotel dept, HK division)",
      common.classify_housekeeping(title="Linen Keeper",
                                   department="Food & Beverage + Hotel",
                                   category="Housekeeping & Laundry"), True)
check("housekeeping(Officer Staff Steward / HOUSEKEEPING dept)",
      common.classify_housekeeping(title="Officer Staff Steward",
                                   department="HOUSEKEEPING",
                                   category="Housekeeping & Laundry"), True)

# --- gate 1: shipboard ---------------------------------------------------- #
check("shipboard(board hint 'ship')",
      common.classify_shipboard(title="Cabin Steward", source_hint="ship")[0], True)
check("shipboard(board hint 'shore')",
      common.classify_shipboard(title="Cabin Steward", source_hint="shore")[0], False)
check("shipboard(Miami office)",
      common.classify_shipboard(title="Inventory Specialist", location="Miami, Florida")[0], False)
check("shipboard(Harvest Caye island)",
      common.classify_shipboard(title="Public Area Attendant",
                                location="Harvest Caye, Belize (Island)",
                                description="Private island resort day-visit operation.")[0], False)
check("shipboard(fleetwide)",
      common.classify_shipboard(title="Cabin Steward", location="Fleetwide (onboard)")[0], True)

# --- role buckets --------------------------------------------------------- #
check("bucket(Stateroom Steward)", common.classify_role_bucket("OCEAN - Stateroom Steward/ess"), "cabin_steward")
check("bucket(Laundry Attendant)", common.classify_role_bucket("Laundry Attendant"), "laundry")
check("bucket(Crew Cleaner)", common.classify_role_bucket("Crew Cleaner"), "utility")
check("bucket(Asst HK Manager)", common.classify_role_bucket("Assistant Housekeeping Manager"), "supervisor")
check("bucket(1st Housekeeper)", common.classify_role_bucket("OCEAN - 1st Housekeeper"), "supervisor")

# --- gate 3: required-experience parsing ---------------------------------- #
for text, want in [
    ("Minimum 2 years of experience in a similar role in a hotel.", 2.0),
    ("At least three years experience in housekeeping.", 3.0),
    ("1-2 years of relevant experience required.", 1.0),
    ("6 months experience in a hotel is required.", 0.5),
    ("No previous experience is required — training provided.", 0.0),
    ("Entry-level position, we will train you.", 0.0),
    # must NOT be mistaken for an experience requirement:
    ("Viking has more than 450 awards and 100 years of history.", None),
    ("Contract length is 8 months.", None),
    ("Founded in 1997, MSC has grown for over 20 years.", None),
    ("", None),
]:
    check(f"years({text[:44]!r})", common.parse_required_years(text), want)

# --- gate 5: freshness ---------------------------------------------------- #
import datetime as _dt
today = _dt.date.today()
check("fresh(today)", common.is_fresh(today.isoformat()), True)
check("fresh(29d)", common.is_fresh((today - _dt.timedelta(days=29)).isoformat()), True)
check("fresh(31d)", common.is_fresh((today - _dt.timedelta(days=31)).isoformat()), False)
check("fresh(no date)", common.is_fresh(""), False)
check("parse_date('Posted 6 Days Ago')",
      common.parse_date("Posted 6 Days Ago"), (today - _dt.timedelta(days=6)).isoformat())
check("parse_date('Posted Today')", common.parse_date("Posted Today"), today.isoformat())

# --- scoring: the shape of the verdict ------------------------------------ #
have = common.kasi_housekeeping_years()
s_steward, v_steward, _ = common.score_match(
    title="Stateroom Steward", description="Minimum 1 year experience in a hotel. English required.",
    role_bucket="cabin_steward", seniority="attendant", req_years=1.0)
check("verdict(Stateroom Steward, asks 1y)", v_steward, "strong_match")

s_dir, v_dir, _ = common.score_match(
    title="Housekeeping Director", description="Minimum 10 years shipboard management experience.",
    role_bucket="supervisor", seniority="director", req_years=10.0)
check("verdict(Housekeeping Director, asks 10y)", v_dir, "not_a_match")

if s_steward <= s_dir:
    FAILS.append(f"a steward role must outscore a director role ({s_steward} vs {s_dir})")

# --- english requirement --------------------------------------------------- #
for text, tier in [
    ("Fluent in English, both spoken and written.", "fluency"),
    ("Fluency in English (oral and written) to communicate effectively.", "fluency"),
    ("Must have solid English communication skills.", "fluency"),
    ("Fluent in written and spoken English", "fluency"),
    ("Intermediate to Advanced verbal and written level of English is required", "fluency"),
    ("A valid Marlins English test certificate is required.", "certificate"),
    ("Candidates must hold IELTS 5.5 or equivalent.", "certificate"),
    ("English language proficiency test required before joining.", "certificate"),
    # must NOT be read as an English requirement:
    ("Proficiency in Computers and MS Excel.", "mentioned" if False else "none"),
    ("Must be proficient with PC based databases and spreadsheets.", "none"),
    ("", "none"),
]:
    check(f"english({text[:46]!r})", common.parse_english_requirement(text)[0], tier)

check("english(certs named)",
      common.parse_english_requirement("A valid Marlins English test certificate is required.")[1] != [], True)

# --- gate 6: exclusions ---------------------------------------------------- #
_saved = common._EXCL_CACHE
common._EXCL_CACHE = [
    {"company": "MSC Cruises", "title_norm": "butler"},
    {"company": "", "title_contains": "laundry"},
]
check("excluded(exact company+title)",
      common.is_excluded({"company": "MSC Cruises", "title": "Butler"})[0], True)
check("excluded(same title, other company)",
      common.is_excluded({"company": "Viking", "title": "Butler"})[0], False)
check("excluded(title_contains, any company)",
      common.is_excluded({"company": "Viking", "title": "Laundry Attendant"})[0], True)
check("excluded(unrelated role)",
      common.is_excluded({"company": "MSC Cruises", "title": "Crew Cleaner"})[0], False)
# a repost under a new requisition id must STAY excluded (we key on title, not id)
check("excluded(repost with new id)",
      common.is_excluded({"company": "MSC Cruises", "title": "Butler", "job_id": "brand-new"})[0], True)
common._EXCL_CACHE = _saved

# --- scam screening for informal leads ------------------------------------- #
import trust as _trust

SCAM = ("URGENT HIRING CRUISE SHIP HOUSEKEEPING ATTENDANT CABIN STEWARD 100% GUARANTEED "
        "JOINING NO INTERVIEW DIRECT SELECTION ONLY 5 SEATS LEFT HURRY REGISTRATION FEE "
        "RS 35,000 PAY VIA GPAY SEND PASSPORT AND CDC COPY ON WHATSAPP +91 9876543210")
LICENSED = ("Hiren International ASST. BEVERAGE OPERATIONS MANAGER EMAIL YOUR CV ON: "
            "HIRENRCG@HIRENINTERNATIONAL.COM RPSL MUM-219 valid till 20-07-2031")
OFFICIAL = "MSC Cruises is hiring Cabin Stewards. Apply at careers.msccruises.com. No fee is charged."

check("scam is high_risk", _trust.assess_trust(SCAM)["band"], "high_risk")
check("licensed agent is not high_risk",
      _trust.assess_trust(LICENSED)["band"] != "high_risk", True)
check("RPSL number extracted", _trust.assess_trust(LICENSED)["rpsl"], "RPSL-MUM-219")
check("official employer post is clean", _trust.assess_trust(OFFICIAL)["band"], "looks_ok")

# A fee demand alone must be enough to reject, however friendly the rest reads.
check("fee demand alone rejects",
      _trust.assess_trust("Join MSC Cruises as Cabin Steward. RPSL-MUM-100. "
                          "Small registration fee of Rs 5000 applies.")["band"], "high_risk")
# ...and the reason must actually mention the money.
check("fee rejection explains itself",
      any("money" in f for f in _trust.assess_trust(SCAM)["flags"]), True)

# An ordinary local advert with only a phone number is 'caution', not 'high_risk' —
# these two signals are one thing and must not be double-counted.
check("bare-mobile advert is caution, not high_risk",
      _trust.assess_trust("COASTAL FLAMES WE ARE HIRING WAITER. "
                          "Send your resume to +91 7887581812")["band"], "caution")

# --- report --------------------------------------------------------------- #
print(f"Kasi's computed housekeeping experience: {have} years")
if FAILS:
    print(f"\n{len(FAILS)} FAILED:\n")
    for f in FAILS:
        print("  ✗ " + f)
    sys.exit(1)
print("All classifier assertions passed.")
