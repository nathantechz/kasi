#!/usr/bin/env python3
"""
trust.py — decide whether an informally-sourced job lead is safe to act on.

Why this exists
---------------
Cruise work is one of the most heavily scammed job markets in India. The usual
fraud is simple: an "agent" on Instagram, Facebook or WhatsApp advertises
shipboard vacancies, then asks the candidate for a registration / placement /
medical / visa fee. The job does not exist.

The legal position matters here and gives us a hard rule. Under India's
Merchant Shipping (Recruitment and Placement of Seafarers) Rules, a licensed
RPSL agent **may not charge a seafarer any fee for placement**. So *any* request
for money from the candidate is either an unlicensed operator or a scam. That
makes a fee demand an automatic rejection rather than a judgement call.

The strongest positive signal is an **RPSL number** — the Recruitment and
Placement Services Licence issued by the Directorate General of Shipping,
written like `RPSL-MUM-219`. A genuine agent advertises it, because they must.

Bands
-----
    high_risk  — removed from the dashboard entirely
    caution    — shown, but badged, with the specific reasons listed
    looks_ok   — shown; still unverified, and still not a guarantee

Nothing here proves a lead is genuine. It only removes the ones that are
clearly unsafe and makes the remaining doubts visible.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Automatic rejection — asking the candidate for money
# --------------------------------------------------------------------------- #
FEE_DEMAND = re.compile(
    r"("
    r"(registration|placement|processing|service|consultanc\w*|agency|training|"
    r"medical|documentation|visa|ticket|joining|security|refundable)\s*"
    r"(fee|fees|charge|charges|amount|deposit|payment)|"
    r"(fee|fees|charges?)\s*(of|:)?\s*(rs\.?|inr|₹|\$)\s*[\d,]+|"
    r"(rs\.?|inr|₹)\s*[\d,]{3,}\s*(only|/-)?\s*(for|towards|to be paid|payable)|"
    r"pay\s*(rs\.?|inr|₹|\$)\s*[\d,]+|"
    r"(candidate|applicant)s?\s*(has|have|must|need|should)?\s*to\s*(pay|bear|deposit)|"
    r"advance\s*payment|"
    r"(gpay|google\s*pay|phonepe|paytm|upi|western\s*union)\b"
    r")", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Positive signals
# --------------------------------------------------------------------------- #
RPSL = re.compile(r"RPSL[\s\-–]*([A-Z]{2,4})[\s\-–]*(\d{1,4})", re.IGNORECASE)
NO_FEE_PLEDGE = re.compile(
    r"(no\s*(placement|registration|service|agency)?\s*fee|"
    r"fee\s*free|we\s*(do\s*not|don'?t)\s*charge|zero\s*fee|"
    r"never\s*pay\s*(any\s*)?(fee|money))", re.IGNORECASE)

CORPORATE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
FREE_EMAIL_HOST = re.compile(
    r"^(gmail|yahoo|ymail|rediffmail|hotmail|outlook|live|icloud|aol|protonmail|mail)\.",
    re.IGNORECASE)

# Cruise lines / crewing brands whose own boards this pipeline already scrapes
# or which are large, verifiable employers.
KNOWN_EMPLOYER = re.compile(
    r"(msc\s*cruises|viking|norwegian cruise|\bNCL\b|oceania|regent seven seas|"
    r"royal caribbean|celebrity cruises|carnival|princess|holland america|"
    r"seabourn|cunard|\bP&O\b|costa|aida|disney cruise|virgin voyages|"
    r"silversea|hurtigruten|explora|lindblad|windstar|ponant|"
    r"columbia|crewlifeatsea|crew life at sea|onespaworld|v\.?ships)",
    re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Risk signals
# --------------------------------------------------------------------------- #
GUARANTEE = re.compile(
    r"(100\s*%\s*(job|placement|guarantee)|guaranteed\s*(job|placement|selection|visa)|"
    r"direct\s*(joining|selection|recruitment)\s*(no|without)|"
    r"no\s*interview|without\s*interview|instant\s*(joining|offer)|"
    r"sure\s*(shot|selection)|confirm\s*joining)", re.IGNORECASE)

URGENCY = re.compile(
    r"(only\s*\d+\s*(seat|slot|vacanc|position)|limited\s*(seat|slot|vacanc)|"
    r"hurry|last\s*date\s*today|immediate\s*joining|urgent\s*joining|"
    r"few\s*(seats|slots)\s*left|apply\s*fast|closing\s*soon)", re.IGNORECASE)

WHATSAPP_ONLY = re.compile(
    r"(whats\s*app|whatsapp|\bwa\.me\b|dm\s*(me|us)\s*(on|for)|"
    r"send\s*(your\s*)?(cv|resume|documents?)\s*(to|on)?\s*\+?\d[\d\s\-]{7,})",
    re.IGNORECASE)

BARE_PHONE = re.compile(r"(\+?\d[\d\s\-]{8,14}\d)")

DOCS_UPFRONT = re.compile(
    r"(send\s*(your\s*)?(passport|cdc|seaman'?s?\s*book)|"
    r"(passport|cdc)\s*(copy|scan|number)\s*(required|needed|send))", re.IGNORECASE)


def assess_trust(text: str, *, source: str = "informal",
                 account: str = "") -> dict:
    """Score one informally-sourced lead.

    Returns {band, risk, flags, positives, rpsl, employer, contact}.
    `risk` runs 0 (clean) to 100 (certain scam pattern).
    """
    t = text or ""
    flags: list[str] = []
    positives: list[str] = []
    risk = 20                      # informal sources start with baseline doubt

    # --- automatic rejection -------------------------------------------- #
    # A fee demand is DISQUALIFYING on its own and cannot be offset. Treating it
    # as just another weight was exploitable: quoting a (possibly fake) RPSL
    # number and naming a real cruise line earned enough trust credit to pull a
    # fee-charging post back down into "caution". Charging a seafarer for
    # placement is unlawful for a licensed agent, so there is no combination of
    # reassuring signals that makes it acceptable. Short-circuit.
    fee = FEE_DEMAND.search(t)
    if fee:
        flags.append(f"asks the candidate for money ('{fee.group(0).strip()[:60]}') — "
                     f"a licensed RPSL agent is forbidden from charging placement fees")
        rpsl_m0 = RPSL.search(t)
        emp_m0 = KNOWN_EMPLOYER.search(t)
        if rpsl_m0 or emp_m0:
            flags.append("quotes a licence number and/or a real cruise line alongside a fee "
                         "demand — a common way to make a scam look official")
        return {"band": "high_risk", "risk": 100, "flags": flags, "positives": [],
                "rpsl": (f"RPSL-{rpsl_m0.group(1).upper()}-{rpsl_m0.group(2)}"
                         if rpsl_m0 else ""),
                "employer": emp_m0.group(0) if emp_m0 else "",
                "contact": ""}

    # --- licence --------------------------------------------------------- #
    rpsl_m = RPSL.search(t)
    rpsl = ""
    if rpsl_m:
        rpsl = f"RPSL-{rpsl_m.group(1).upper()}-{rpsl_m.group(2)}"
        positives.append(f"quotes a DG Shipping licence ({rpsl}) — verifiable on dgshipping.gov.in")
        risk -= 25

    if NO_FEE_PLEDGE.search(t):
        positives.append("states explicitly that no fee is charged")
        risk -= 8

    # --- who is the employer --------------------------------------------- #
    emp_m = KNOWN_EMPLOYER.search(t)
    employer = emp_m.group(0) if emp_m else ""
    if employer:
        positives.append(f"names a known employer ({employer})")
        risk -= 12
    else:
        flags.append("does not name a verifiable cruise line or licensed employer")
        risk += 12

    # --- contact route ---------------------------------------------------- #
    emails = CORPORATE_EMAIL.findall(t)
    contact = ""
    corporate = [e for e in emails if not FREE_EMAIL_HOST.match(e)]
    free = [e for e in emails if FREE_EMAIL_HOST.match(e)]
    if corporate:
        contact = f"email @{corporate[0]}"
        positives.append(f"applications go to a company domain (@{corporate[0]})")
        risk -= 12
    if free:
        flags.append(f"collects CVs at a free email address (@{free[0]}) rather than a company domain")
        risk += 15

    # WhatsApp-only and bare-mobile-only are the SAME underlying signal ("no
    # traceable company channel"). Count it once, or an ordinary local advert
    # stacks two penalties and lands in high_risk on its own.
    phone = BARE_PHONE.search(t)
    if not corporate:
        if WHATSAPP_ONLY.search(t):
            flags.append("routes applicants to WhatsApp/DM rather than a company address")
            risk += 22
        elif phone and not emails:
            contact = contact or f"phone {phone.group(0).strip()}"
            flags.append("a bare mobile number is the only way to apply — no company, no domain")
            risk += 18

    # --- classic scam language -------------------------------------------- #
    g = GUARANTEE.search(t)
    if g:
        flags.append(f"promises a guaranteed outcome ('{g.group(0).strip()[:40]}')")
        risk += 30
    u = URGENCY.search(t)
    if u:
        flags.append(f"manufactured urgency ('{u.group(0).strip()[:40]}')")
        risk += 12
    d = DOCS_UPFRONT.search(t)
    if d:
        flags.append("asks for passport/CDC before any interview")
        risk += 18

    risk = max(0, min(100, risk))
    if risk >= 60:
        band = "high_risk"
    elif risk >= 32:
        band = "caution"
    else:
        band = "looks_ok"

    return {"band": band, "risk": risk, "flags": flags, "positives": positives,
            "rpsl": rpsl, "employer": employer, "contact": contact}


if __name__ == "__main__":
    samples = [
        ("Hiren International RPSL MUM-219 valid till 2031. Email your CV on HIRENRCG@HIRENINTERNATIONAL.COM", "licensed agent"),
        ("WE ARE HIRING HOUSEKEEPER. Registration fee Rs 25,000. 100% guaranteed joining. WhatsApp +91 9876543210", "textbook scam"),
        ("COASTAL FLAMES WE ARE HIRING WAITER. Send your resume to +91 7887581812", "bare mobile"),
        ("MSC Cruises hiring Cabin Steward. Apply at careers.msccruises.com. No fee is charged.", "clean"),
    ]
    for text, label in samples:
        r = assess_trust(text)
        print(f"\n{label}: {r['band']} (risk {r['risk']})  rpsl={r['rpsl'] or '-'}")
        for f in r["flags"]:
            print("   ! " + f)
        for p in r["positives"]:
            print("   + " + p)
