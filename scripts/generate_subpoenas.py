#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Generate the 10 individual Subpoena Duces Tecum packets + master Notice of Subpoenas.

Parses the subpoena source documents:
    25FA152/NOV_10/02_DISCOVERY/SUBPOENA_DUCES_TECUM_INDEX.md    (custodian list)
    25FA152/NOV_10/02_DISCOVERY/SUBPOENA_DUCES_TECUM_RIDERS.md  (riders + Rule 236 form)

Emits, for each custodian, a ready-to-issue packet containing:
    1. Circuit Court Subpoena Duces Tecum face sheet (735 ILCS 5/2-1101)
    2. The custodian's verbatim production rider
    3. The blank Rule 236 / IRE 902(11) Custodian of Records Certification

Plus a unified master Notice of Subpoenas directed to Respondent and the GAL.

PDF rendering is DELEGATED to motion_to_pdf.py (the single source of truth for
court-ready rendering). This script never renders PDFs itself.

Usage:
    uv run dc13_hive/scripts/generate_subpoenas.py
    uv run dc13_hive/scripts/generate_subpoenas.py --dry-run
    uv run dc13_hive/scripts/generate_subpoenas.py --issue-date 2026-10-05
    uv run dc13_hive/scripts/generate_subpoenas.py --no-pdf

Arguments:
    --dry-run         List the custodians and outputs; write nothing, render nothing
    --issue-date      Date the subpoenas issue / are served (default: 2026-10-05)
    --service-date    Date service is completed for the Notice (default: today)
    --hearing-date    Consolidated hearing date (default: 2026-11-10)
    --hearing-time    Consolidated hearing time (default: 9:00 AM)
    --no-pdf          Generate markdown only; skip motion_to_pdf.py
    --force           Re-render PDFs even if the .pdf is newer than the .md

Address provenance: street addresses below are transcribed from the case record
(see ADDRESS_PROVENANCE). Where the record does not contain a street address, the
packet emits a bracketed VERIFY placeholder rather than a fabricated address --
an incorrectly addressed subpoena is unenforceable. Verify every custodian's
address of record and Privacy/HIM contact before issuance.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

INDEX_MD = REPO_ROOT / "25FA152" / "NOV_10" / "02_DISCOVERY" / "SUBPOENA_DUCES_TECUM_INDEX.md"
RIDERS_MD = REPO_ROOT / "25FA152" / "NOV_10" / "02_DISCOVERY" / "SUBPOENA_DUCES_TECUM_RIDERS.md"

OUT_DIR = REPO_ROOT / "25FA152" / "NOV_10" / "SUBPOENAS"
PRINT_DIR = REPO_ROOT / "25FA152" / "PRINT" / "NOV_10" / "SUBPOENAS"

MOTION_TO_PDF = REPO_ROOT / "dc13_hive" / "scripts" / "motion_to_pdf.py"

# motion_to_pdf.py carries its own PEP 723 dependency block, so it must be
# launched through uv (not this script's dependency-free interpreter).
UV = shutil.which("uv") or "uv"

# ---------------------------------------------------------------------------
# Case constants
# ---------------------------------------------------------------------------

# Caption style per LEGAL_FILE/01_DRAFTS/PETITION_TO_MODIFY.md: court header on a
# single bold line, uppercase party names, no redundant "IN RE THE PARENTING
# TIME..." line. Keeping the header as ONE markdown paragraph renders as one
# caption block and preserves vertical space (verified 2026-09-30).
COURT_LINE_1 = "IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL"
COURT_LINE_2 = "CIRCUIT, DEKALB COUNTY, ILLINOIS"
CASE_NO_LINE = "Case Nos. 25FA152 (Consolidated with 26OP158)"
JUDGE_LINE = "Hon. Sarah Gallagher-Chami, Room 330"
COURTHOUSE = "DeKalb County Courthouse, 133 W. State St., Sycamore, IL 60178"
CLERK_NAME = "LORI GRUBBS, Clerk of the Circuit Court"

PETITIONER_BLOCK = [
    "David C. Byers, Petitioner Pro Se",
    "506 N. 1st St., Apt. 9",
    "DeKalb, IL 60115",
    "(815) 322-1013 | dcbyers13@gmail.com",
]

RESPONDENT_EMAIL = "paulettadonatello@gmail.com"
GAL_EMAIL = "evan@evankinglaw.com"

MINOR_DOB = "July 16, 2013"

DEFAULT_ISSUE_DATE = "October 1, 2026"
DEFAULT_HEARING_DATE = "November 10, 2026"
DEFAULT_HEARING_TIME = "9:00 AM"

SUBPOENA_SLUGS = {
    1: "CENTERPOINTE",
    2: "BEN_GORDON",
    3: "MIND_MATTERS",
    4: "MERCY",
    5: "STREAMWOOD",
    6: "SSM_DEPAUL",
    7: "PARKLAND",
    8: "DAYBREAK",
    9: "ELLIE",
    10: "DEKALB_CUSD_428",
}

# Custodian service block per rider number.
# address_line: verified street address, or a VERIFY placeholder when the case
# record does not contain one.
# ADDRESS_PROVENANCE documents where each address was transcribed from.
CUSTODIANS = {
    1: {
        "name": "CenterPointe Hospital of Columbia",
        "address_line": "1201 International Drive, Columbia, Missouri 65202",
        "attn": "Health Information Management Department / Custodian of Records",
        "verify": False,
    },
    2: {
        "name": "Ben Gordon Center (Northwestern Medicine)",
        "address_line": "12 Health Services Drive, DeKalb, Illinois 60115",
        "attn": "Health Information Management / Custodian of Records",
        "verify": False,
    },
    3: {
        "name": "Mind Matters (Annie Barsch, MA, LMFT, CCTP)",
        "address_line": "313 N. Main St., Elburn, Illinois 60119",
        "attn": "Annie Barsch, MA, LMFT, CCTP / Custodian of Records",
        "verify": False,
    },
    4: {
        "name": "Mercy Medical Center",
        "address_line": "1325 N. Highland Avenue, Aurora, Illinois 60506",
        "attn": "Health Information Management / Custodian of Records",
        "verify": False,
    },
    5: {
        "name": "Streamwood Behavioral Healthcare System",
        "address_line": "1400 E. Irving Park Rd., Streamwood, Illinois 60107",
        "attn": "Health Information Management / Custodian of Records",
        "verify": False,
    },
    6: {
        "name": "SSM Health Behavioral Medicine Center / DePaul",
        "address_line": "12303 DePaul Drive, Bridgeton/St. Louis, Missouri 63044",
        "attn": "Health Information Management / Custodian of Records",
        "verify": False,
    },
    7: {
        "name": "Parkland Health Center -- Emergency Department",
        "address_line": "1101 W. Liberty St., Farmington, Missouri 63640",
        "attn": "Emergency Department / Custodian of Records",
        "verify": False,
    },
    8: {
        "name": "Daybreak Health (telehealth -- corporate headquarters)",
        "address_line": (
            "548 Market Street, Suite 38798, San Francisco, California 94104 "
            "(virtual practice; no Illinois office)"
        ),
        "attn": (
            "Privacy Officer / Custodian of Records; serve by electronic mail at "
            "carecoordinator@daybreakhealth.com and christinecauwels@daybreakhealth.com"
        ),
        "verify": False,
    },
    9: {
        "name": "Ellie Mental Health (Jennyfer Garcia, LCSW)",
        "address_line": "2570 Foxfield Rd., Ste. 200, St. Charles, Illinois 60174",
        "attn": "Jennyfer Garcia, LCSW / Custodian of Records; (847) 403-3535",
        "verify": False,
    },
    10: {
        "name": "DeKalb Community Unit School District #428",
        "address_line": (
            "c/o Clinton Rosette Middle School, 240 S. 6th St., DeKalb, Illinois 60115 "
            "(in coordination with Huntley Middle School, 1515 S. 4th St., "
            "DeKalb, Illinois 60115)"
        ),
        "attn": "Custodian of Student Records / Registrar",
        "verify": False,
    },
}

# Where each street address above was transcribed from within the case record.
ADDRESS_PROVENANCE = {
    1: "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md (CenterPointe, 1201 International Dr)",
    2: "Northwestern Medicine Ben Gordon Center, 12 Health Services Drive, DeKalb, IL 60115",
    3: "MOTION_ADDRESS_ALIENATION_AND_ENDANGERMENT.md (Mind Matters, 313 N Main St)",
    4: "Mercy Medical Center, 1325 N. Highland Ave., Aurora, IL 60506",
    5: "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md (Streamwood, 1400 E Irving Park Rd)",
    6: "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md (SSM/DePaul, 12303 DePaul Dr)",
    7: "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md (Parkland, 1101 W Liberty St)",
    8: "Daybreak Health corporate headquarters, 548 Market St., Ste. 38798, San Francisco, CA 94104 "
       "(virtual practice; no Illinois office)",
    9: "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md (Ellie, 2570 Foxfield Rd Ste 200)",
    10: "SUBPOENA_DUCES_TECUM_RIDERS.md Rider 10 (Clinton Rosette / Huntley MS)",
}

VERIFY_MARKER = (
    "**ADDRESS VERIFICATION REQUIRED:** The case record does not contain a street "
    "address for this producing entity. Confirm the current Health Information "
    "Management / Privacy Office address of record before issuance. An incorrectly "
    "addressed subpoena duces tecum is unenforceable."
)

PAGE_BREAK = '<div style="page-break-before: always;"></div>'

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_index(path):
    """Return ordered list of dicts, one per custodian row in the index table."""
    if not path.is_file():
        sys.exit(f"ERROR: index not found: {path}")

    rows = []
    row_re = re.compile(r"^\|\s*(\d+)\s*\|(.+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = row_re.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 2:
            continue
        # The leading numeric column was already captured as the row key, so
        # cells[0] is the entity name; the separator row is rejected above.
        num = int(m.group(1))
        rows.append(
            {
                "num": num,
                "entity": cells[0],
                "records_sought": cells[1] if len(cells) > 1 else "",
                "status": cells[2] if len(cells) > 2 else "",
                "notes": cells[3] if len(cells) > 3 else "",
            }
        )

    if not rows:
        sys.exit(f"ERROR: no custodian rows parsed from {path}")
    return sorted(rows, key=lambda r: r["num"])


def parse_riders(path):
    """Return (riders, cert_form).

    riders: {int: {"heading": str, "body": str}} -- body verbatim from the
            source document, suitable for direct markdown emission.
    cert_form: str -- the blank Rule 236 custodian certification (Section XII).
    """
    if not path.is_file():
        sys.exit(f"ERROR: riders not found: {path}")

    text = path.read_text(encoding="utf-8")

    # Split on "## <roman>. PRODUCTION RIDER NO. <n> -- <title>"
    rider_re = re.compile(
        r"^##\s+[IVX]+\.\s+PRODUCTION RIDER NO\.\s*(\d+)\s*[—\-]+\s*(.+?)\s*$",
        re.MULTILINE,
    )
    marks = list(rider_re.finditer(text))
    if not marks:
        sys.exit(f"ERROR: no production riders parsed from {path}")

    riders = {}
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # Trim trailing separators / change log from the final rider.
        body = text[start:end]
        body = re.split(r"^##\s+[IVX]+\.\s+CUSTODIAN OF RECORDS", body, flags=re.MULTILINE)[0]
        body = re.split(r"^##\s+[IVX]+\.\s+CHANGE LOG", body, flags=re.MULTILINE)[0]
        body = re.sub(r"(?:\n---\s*)+$", "", body)
        riders[int(m.group(1))] = {
            "heading": f"PRODUCTION RIDER NO. {m.group(1)} — {m.group(2)}",
            "body": body.strip("\n"),
        }

    # Section XII -- blank custodian certification form.
    cert_match = re.search(
        r"^##\s+[IVX]+\.\s+CUSTODIAN OF RECORDS CERTIFICATION.*?$", text, flags=re.MULTILINE
    )
    if not cert_match:
        sys.exit(f"ERROR: Rule 236 certification form not found in {path}")

    cert_text = text[cert_match.end():]
    cert_text = re.split(r"^##\s+[IVX]+\.\s+CHANGE LOG", cert_text, flags=re.MULTILINE)[0]
    cert_text = re.sub(r"^---\s*$", "", cert_text, flags=re.MULTILINE)
    cert_form = cert_text.strip("\n")

    # Ensure HTML span underlines for date blanks so markdown does not swallow them
    day_blank = '<span style="text-decoration: underline;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    month_blank = '<span style="text-decoration: underline;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    cert_form = re.sub(
        r"Executed this (?:\\_|_|<[^>]+>|&nbsp;)+ day of (?:\\_|_|<[^>]+>|&nbsp;)+, 2026\.",
        f"Executed this {day_blank} day of {month_blank}, 2026.",
        cert_form,
    )
    cert_form = re.sub(
        r"Subscribed and sworn to before me this (?:\\_|_|<[^>]+>|&nbsp;)+ day of (?:\\_|_|<[^>]+>|&nbsp;)+, 2026\.",
        f"Subscribed and sworn to before me this {day_blank} day of {month_blank}, 2026.",
        cert_form,
    )
    cert_form = re.sub(
        r"My commission expires: (?:\\_|_|<[^>]+>|&nbsp;)+",
        f"My commission expires: {month_blank}",
        cert_form,
    )
    # Ensure caption line break in Attachment B
    cert_form = re.sub(
        r"\*\*IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL CIRCUIT[,\s]*DEKALB COUNTY,[ \t]*ILLINOIS\*\*",
        f"**{COURT_LINE_1}**  \n**{COURT_LINE_2}**",
        cert_form,
    )
    cert_form = re.sub(
        r"\*\*IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL CIRCUIT\*\*\s*\n\s*\*\*DEKALB COUNTY, ILLINOIS\*\*",
        f"**{COURT_LINE_1}**  \n**{COURT_LINE_2}**",
        cert_form,
    )
    cert_form = re.sub(
        r"\*\*(Signature of Custodian|Printed Name / Title|Notary Public)\*\*",
        r"<strong>\1</strong>",
        cert_form,
    )

    return riders, cert_form


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def caption_block(title):
    """Standard caption, matching the filestamped NOV_10 pleadings.

    Court header on two lines; uppercase party names; no redundant
    "IN RE THE PARENTING TIME..." line. Each element is bold and separated by a
    blank line -- motion_to_pdf.py merges adjacent markdown lines into a single
    paragraph, which would otherwise run the caption elements together on the
    rendered page. `title` is passed WITHOUT its own ** delimiters.
    """
    lines = [
        f"**{COURT_LINE_1}**  \n**{COURT_LINE_2}**",
        "",
        "**DAVID C. BYERS**, Petitioner,",
        "",
        "vs.",
        "",
        "**PAULETTA D. DONATELLO**, Respondent.",
        "",
        f"**{CASE_NO_LINE}**",
        "",
        f"**{JUDGE_LINE}**",
        "",
        f"**{title}**",
    ]
    return "\n".join(lines)


def build_packet(row, rider, cert_form, cfg):
    """Render one complete subpoena packet as markdown.

    Three-part layout:
        Part I   -- Subpoena face sheet (Page 1), including the Circuit Clerk
                    issuance/seal block and the Petitioner pro se signature.
        Part II  -- Production Rider (Attachment A), verbatim.
        Part III -- Blank Custodian Certification Affidavit (Attachment B).
    """
    num = row["num"]
    cust = CUSTODIANS.get(num, {})

    entity_name = cust.get("name", row["entity"])
    address_line = cust.get("address_line", "[ADDRESS TO BE VERIFIED]")
    attn = cust.get("attn", "Custodian of Records")
    needs_verify = cust.get("verify", True)

    out = []
    out.append(caption_block("SUBPOENA DUCES TECUM"))
    out.append("")

    # ---- Addressee (compact: single block, hard line breaks) -------------
    out.append(f"**TO:** {entity_name}  \n"
               f"{address_line}  \n"
               f"**ATTN:** {attn}")
    out.append("")
    if needs_verify:
        out.append(VERIFY_MARKER)
        out.append("")

    # ---- Return date ---------------------------------------------------
    out.append(f"**RETURN DATE: {cfg['hearing_date']} at {cfg['hearing_time']}, "
               f"{JUDGE_LINE}, {COURTHOUSE}**")
    out.append("")

    # ---- Command -------------------------------------------------------
    out.append("**YOU ARE HEREBY COMMANDED** pursuant to **735 ILCS 5/2-1101** to produce, at "
               "the consolidated evidentiary hearing in these causes, the records and "
               f"documents described in **Production Rider No. {num}**, annexed as "
               "**Attachment A** and incorporated herein as if fully set forth, together "
               "with certified copies thereof, so that the records may be admitted without "
               "live testimony under **Ill. Sup. Ct. R. 236** and **Ill. R. Evid. 902(11)**.")
    out.append("")

    # ---- Alternative compliance -----------------------------------------
    out.append("**ALTERNATIVE COMPLIANCE.** Compliance may be satisfied **without personal "
               "appearance** by mailing certified copies with the completed **Custodian of "
               "Records Certification Affidavit** reproduced as **Attachment B** to the "
               "Clerk of the Court / Petitioner. Any objection shall be served in writing "
               "upon Petitioner and filed with this Honorable Court **on or before the "
               "Return Date**, identifying the specific statutory ground relied upon. Scope "
               f"is limited to records concerning the minor child, **{MINOR_DOB}**, for the "
               "period stated in Attachment A.")
    out.append("")

    # ---- Circuit Clerk issuance & seal block (must stay on Page 1) -------
    out.append("**ISSUANCE BY THE CLERK OF THE CIRCUIT COURT.** Issued by the Clerk of the "
               "Circuit Court of the Twenty-Third Judicial Circuit, DeKalb County, Illinois, "
               "pursuant to **735 ILCS 5/2-1101** (\"[a]n order of court is not required to "
               "obtain the issuance by the clerk ... of a subpoena duces tecum.\").")
    out.append("")
    out.append(f"**{CLERK_NAME}**  \n"
               'By: <span style="text-decoration: underline;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>, Deputy Clerk  \n'
               "**SEAL:**  \n"
               f"**Date of issuance:** {cfg['issue_date']}")
    out.append("")
    out.append('<div style="break-inside: avoid; page-break-inside: avoid;">'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 22pt; margin-bottom: 4px;"></div>'
               'David C. Byers, Petitioner Pro Se<br>'
               '506 N. 1st St., Apt. 9, DeKalb, IL 60115<br>'
               '(815) 322-1013 | dcbyers13@gmail.com'
               '</div>')
    out.append("")

    if needs_verify:
        out.append(f"**Address source:** "
                   + (ADDRESS_PROVENANCE.get(num, "unverified") or "unverified") + ".")
        out.append("")

    # ---- Part II: the production rider (Attachment A) --------------------
    out.append(PAGE_BREAK)
    out.append(f"## PART II — ATTACHMENT A — {rider['heading']}")
    out.append("")

    rider_body = rider["body"]
    # Defensive cleanup of any internal references
    rider_body = re.sub(r"\*?\(Verbatim production rider as adopted in.*?\)\*?", "", rider_body)
    rider_body = re.sub(r"\(corroborates Part A Phase 4.*?\)", "", rider_body)
    rider_body = re.sub(
        r"\(of the MMIL record chain: admission photo/141-page treatment record\)",
        "(including admission photo and 141-page treatment record)",
        rider_body,
    )
    rider_body = re.sub(
        r"\(BCBS claims show 0 individual claims\)",
        "(mandating follow-up individual therapy)",
        rider_body,
    )
    rider_body = re.sub(r"LEGAL_FILE/04_DONATELLO_FILINGS/2026_04_28_EXHIBIT_C_STREAMWOOD\.md",
                        "Respondent's Exhibit C, filed April 28, 2026", rider_body)
    rider_body = re.sub(r"COMMS/RECORDS_REQUEST_DAYBREAK_HEALTH_MAY_21-JUN_25_2026\.md",
                        "Petitioner's Records Request of May 21, 2026", rider_body)
    rider_body = re.sub(r"LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/ELLIE_MENTAL_HEALTH_ROI_REQUEST_07_2026\.md",
                        "Records Request of July 24, 2026", rider_body)
    rider_body = re.sub(r"\b[\w/-]+\.md\b", "", rider_body)
    out.append(rider_body.strip())
    out.append("")

    # ---- Part III: the Rule 236 certification (Attachment B) -------------
    out.append(PAGE_BREAK)
    out.append("")
    out.append("## PART III — ATTACHMENT B — CUSTODIAN OF RECORDS CERTIFICATION "
               "AFFIDAVIT (RULE 236 / IRE 902(11))")
    out.append("")
    out.append("*(To be completed and executed by the producing custodian and returned with the production.)*")
    out.append("")
    out.append(f"{COURT_LINE_1}  \n{COURT_LINE_2}")
    out.append("")
    out.append("DAVID C. BYERS, Petitioner,  \nvs.  \nPAULETTA D. DONATELLO, Respondent.")
    out.append("")
    out.append(f"{CASE_NO_LINE}  \n{JUDGE_LINE}")
    out.append("")
    out.append("**CUSTODIAN OF RECORDS CERTIFICATION PURSUANT TO ILLINOIS SUPREME COURT RULE 236**")
    out.append("")
    out.append("I, the undersigned, being duly sworn, depose and state:")
    out.append("")
    out.append(f"1. I am the custodian of records (or otherwise qualified officer/employee with knowledge) for {entity_name}, located at {address_line}.")
    out.append("")
    out.append("2. The attached records are the original or exact duplicate of the original records maintained in the ordinary course of business of said entity.")
    out.append("")
    out.append("3. The records were made at or near the time of the matter recorded by a person with knowledge of the matters recorded, or from information transmitted by such person.")
    out.append("")
    out.append("4. The records were kept in the course of a regularly conducted business activity, and it was the regular practice of that business activity to make such records.")
    out.append("")
    out.append(f"5. Attached records constitute the complete certified production responsive to the Subpoena Duces Tecum and Production Rider served on {cfg['issue_date']}.")
    out.append("")
    out.append("6. These records are submitted pursuant to **Illinois Supreme Court Rule 236** to permit admission into evidence without further foundation or testimony.")
    out.append("")
    day_blank = '<span style="text-decoration: underline;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    month_blank = '<span style="text-decoration: underline;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>'
    out.append(f"Executed this {day_blank} day of {month_blank}, 2026.")
    out.append("")
    out.append('<div style="break-inside: avoid; page-break-inside: avoid;">\n'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 22pt; margin-bottom: 4px;"></div>\n'
               '<strong>Signature of Custodian</strong><br>\n'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 18pt; margin-bottom: 4px;"></div>\n'
               '<strong>Printed Name / Title</strong>\n'
               '</div>')
    out.append("")
    out.append('<div style="break-inside: avoid; page-break-inside: avoid; margin-top: 14pt;">\n'
               f'Subscribed and sworn to before me this {day_blank} day of {month_blank}, 2026.<br>\n'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 22pt; margin-bottom: 4px;"></div>\n'
               '<strong>Notary Public</strong><br>\n'
               f'My commission expires: {month_blank}\n'
               '</div>')
    out.append("")

    return "\n".join(out)


def build_notice(rows, cfg):
    """Render the unified master Notice of Subpoenas Duces Tecum."""
    out = []
    out.append(caption_block(
        "NOTICE OF FILING AND SERVICE OF SUBPOENAS DUCES TECUM"))
    out.append("")

    out.append(f"TO: **Pauletta D. Donatello**, Respondent, appearing pro se, and any "
               f"counsel of record for Respondent; and **Evan King**, Guardian ad Litem "
               f"({GAL_EMAIL}).")
    out.append("")
    out.append(f"PLEASE TAKE NOTICE that on {cfg['issue_date']}, the Petitioner, "
               "David C. Byers, appearing pro se, caused to be issued and served **ten "
               "(10) Subpoenas Duces Tecum** upon the non-parties identified below, "
               "directed to the Custodian of Records of each producing entity. "
               f"The Return Date and Time for each subpoena is **{cfg['hearing_date']} "
               f"at {cfg['hearing_time']}**, {JUDGE_LINE}, {COURTHOUSE}.")
    out.append("")

    out.append("## I. SUBPOENAS ISSUED")
    out.append("")

    for row in rows:
        num = row["num"]
        cust = CUSTODIANS.get(num, {})
        name = cust.get("name", row["entity"])
        addr = cust.get("address_line", "[ADDRESS TO BE VERIFIED]")
        attn = cust.get("attn", "Custodian of Records")
        out.append(
            f"{num}. **{name}**  \n"
            f"   **Service Address:** {addr}  \n"
            f"   **Attn:** {attn}  \n"
            f"   **Date Issued:** {cfg['issue_date']}  \n"
            f"   **Return Date:** {cfg['hearing_date']} at {cfg['hearing_time']}, Room 330"
        )
        out.append("")

    out.append("## II. RECORDS SOUGHT")
    out.append("")
    out.append("The Production Rider annexed to each subpoena identifies the specific "
               "records sought of that custodian, drawn from the completed "
               "four-hospitalization clinical arc and the treating outpatient providers. "
               "Each production must be certified under **Illinois Supreme Court Rule "
               "236** and **Illinois Rule of Evidence 902(11)** so that the records may "
               "be admitted without the personal appearance of the custodian.")
    out.append("")

    out.append("## III. ALTERNATIVE COMPLIANCE WITHOUT PERSONAL APPEARANCE")
    out.append("")
    out.append("**Compliance may be satisfied without personal appearance by mailing "
               "certified copies accompanied by the attached Rule 236 Certification "
               "Affidavit to the Clerk of the Court / Petitioner.** Each subpoena so "
               "provides. Any objection shall be served in writing and filed with this "
               "Honorable Court on or before the Return Date, citing the specific "
               "statutory ground relied upon.")
    out.append("")

    out.append("## IV. RESERVATION")
    out.append("")
    out.append("Petitioner reserves all rights, including the right to move to compel, to "
               "quash, or to modify any subpoena under **735 ILCS 5/2-1101**, the right to "
               "seek sanctions, and the right to present the resulting records at the "
               "consolidated hearing. No waiver of any objection or defense is intended.")
    out.append("")

    out.append("## V. VERIFICATION")
    out.append("")
    out.append("Under penalties as provided by law pursuant to Section 1-109 of the Code "
               "of Civil Procedure (735 ILCS 5/1-109), the undersigned certifies that the "
               "statements set forth in this instrument are true and correct, except as to "
               "matters therein stated to be on information and belief and as to such "
               "matters the undersigned certifies as aforesaid that he verily believes the "
               "same to be true.")
    out.append("")

    out.append("Respectfully submitted,")
    out.append("")
    out.append('<div style="break-inside: avoid; page-break-inside: avoid;">'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 22pt; margin-bottom: 4px;"></div>'
               'David C. Byers, Petitioner Pro Se<br>'
               '506 N. 1st St., Apt. 9<br>'
               'DeKalb, IL 60115<br>'
               '(815) 322-1013 | dcbyers13@gmail.com'
               '</div>')
    out.append(PAGE_BREAK)
    out.append("")
    out.append("**CERTIFICATE OF SERVICE**")
    out.append("")
    out.append(f"I, David C. Byers, certify that on **{cfg['service_date']}**, I served a "
               "true and correct copy of the foregoing **Notice of Filing and Service of "
               "Subpoenas Duces Tecum**, together with copies of the ten Subpoenas "
               "Duces Tecum and their annexed Production Riders, upon:")
    out.append("")
    out.append("1. **Evan King, Guardian ad Litem**, via electronic mail to "
               f"{GAL_EMAIL};")
    out.append("")
    out.append("2. **Pauletta D. Donatello**, Respondent, via electronic service through "
               "the Odyssey e-filing system (eFileIL) and via electronic mail to "
               f"{RESPONDENT_EMAIL}; and")
    out.append("")
    out.append("3. Any counsel of record for Respondent, via electronic service through "
               "the Odyssey e-filing system (eFileIL), to the extent an attorney of record "
               "has appeared.")
    out.append("")
    out.append('<div style="break-inside: avoid; page-break-inside: avoid;">'
               '<div style="border-bottom: 1px solid black; width: 280px; margin-top: 22pt; margin-bottom: 4px;"></div>'
               'David C. Byers, Petitioner Pro Se'
               '</div>')
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Output + rendering
# ---------------------------------------------------------------------------


def needs_render(src_md, dst_pdf):
    if not dst_pdf.exists():
        return True
    return os.path.getmtime(src_md) > os.path.getmtime(dst_pdf)


def render_pdf(src_md, dst_pdf):
    """Delegate rendering to motion_to_pdf.py -- the single rendering source.

    motion_to_pdf.py declares its own inline PEP 723 dependency metadata
    (markdown, weasyprint, beautifulsoup4, pymupdf), so it MUST be launched
    through `uv run` rather than with this script's bare interpreter.
    """
    dst_pdf.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        UV, "run", str(MOTION_TO_PDF),
        str(src_md), str(dst_pdf), "--margin", "0.72",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return proc.returncode == 0, (proc.stderr or "")[-400:]


def main():
    ap = argparse.ArgumentParser(description="Generate subpoena duces tecum packets.")
    ap.add_argument("--dry-run", action="store_true", help="Preview only; write nothing")
    ap.add_argument("--issue-date", default=DEFAULT_ISSUE_DATE, help="Subpoena issue date")
    ap.add_argument("--service-date",
                    default=None,
                    help="Certificate-of-service date (default: issue date)")
    ap.add_argument("--hearing-date", default=DEFAULT_HEARING_DATE)
    ap.add_argument("--hearing-time", default=DEFAULT_HEARING_TIME)
    ap.add_argument("--no-pdf", action="store_true", help="Markdown only; skip rendering")
    ap.add_argument("--force", action="store_true", help="Re-render even if up to date")
    args = ap.parse_args()

    cfg = {
        "issue_date": args.issue_date,
        "service_date": args.service_date or args.issue_date,
        "hearing_date": args.hearing_date,
        "hearing_time": args.hearing_time,
    }

    rows = parse_index(INDEX_MD)
    riders, cert_form = parse_riders(RIDERS_MD)

    missing = [r["num"] for r in rows if r["num"] not in riders]
    if missing:
        sys.exit(f"ERROR: no production rider parsed for custodian(s): {missing}")

    print(f"Index:  {INDEX_MD.relative_to(REPO_ROOT)}  ({len(rows)} custodians)")
    print(f"Riders: {RIDERS_MD.relative_to(REPO_ROOT)}  ({len(riders)} riders + Rule 236 form)")
    print(f"Output: {OUT_DIR.relative_to(REPO_ROOT)}")
    print(f"Print:  {PRINT_DIR.relative_to(REPO_ROOT)}")
    print(f"Issue date: {cfg['issue_date']}   Return: {cfg['hearing_date']} "
          f"{cfg['hearing_time']}")
    print()

    if args.dry_run:
        for row in rows:
            num = row["num"]
            slug = SUBPOENA_SLUGS.get(num, f"CUSTODIAN_{num:02d}")
            cust = CUSTODIANS.get(num, {})
            flag = "  [ADDRESS VERIFY]" if cust.get("verify") else ""
            print(f"  {num:>2}. SUBPOENA_{num:02d}_{slug}.md  "
                  f"-> {cust.get('name', row['entity'])}{flag}")
        print(f"\n  + NOTICE_OF_SUBPOENAS_DUCES_TECUM.md ({len(rows)} rows)")
        print("\nDry run -- nothing written.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRINT_DIR.mkdir(parents=True, exist_ok=True)

    written = []
    for row in rows:
        num = row["num"]
        slug = SUBPOENA_SLUGS.get(num, f"CUSTODIAN_{num:02d}")
        fname = f"SUBPOENA_{num:02d}_{slug}.md"
        md = build_packet(row, riders[num], cert_form, cfg)
        (OUT_DIR / fname).write_text(md, encoding="utf-8")
        written.append((num, fname, row["entity"]))

    notice_name = "NOTICE_OF_SUBPOENAS_DUCES_TECUM.md"
    (OUT_DIR / notice_name).write_text(build_notice(rows, cfg), encoding="utf-8")

    print(f"{'FILE':<46} {'RENDER':<10} NOTES")
    print("-" * 78)

    failures = []
    for num, fname, entity in written:
        src = OUT_DIR / fname
        dst = PRINT_DIR / fname.replace(".md", ".pdf")
        cust = CUSTODIANS.get(num, {})
        note = "ADDRESS VERIFY" if cust.get("verify") else ""

        if args.no_pdf:
            print(f"{fname:<46} {'(skipped)':<10} {note}")
            continue

        if not args.force and not needs_render(src, dst):
            print(f"{fname:<46} {'up to date':<10} {note}")
            continue

        ok, err = render_pdf(src, dst)
        if ok and dst.exists() and dst.stat().st_size > 0:
            print(f"{fname:<46} {'SUCCESS':<10} {note}")
        else:
            print(f"{fname:<46} {'FAILED':<10} {note}")
            failures.append(fname)
            if err:
                print(f"    {err.strip()}")

    # Master notice.
    src = OUT_DIR / notice_name
    dst = PRINT_DIR / notice_name.replace(".md", ".pdf")
    if args.no_pdf:
        print(f"{notice_name:<46} {'(skipped)':<10}")
    elif not args.force and not needs_render(src, dst):
        print(f"{notice_name:<46} {'up to date':<10}")
    else:
        ok, err = render_pdf(src, dst)
        if ok and dst.exists() and dst.stat().st_size > 0:
            print(f"{notice_name:<46} {'SUCCESS':<10}")
        else:
            print(f"{notice_name:<46} {'FAILED':<10}")
            failures.append(notice_name)
            if err:
                print(f"    {err.strip()}")

    verify_count = sum(1 for r in rows if CUSTODIANS.get(r["num"], {}).get("verify"))
    print("-" * 78)
    print(f"Wrote {len(written)} packets + 1 master notice to {OUT_DIR.relative_to(REPO_ROOT)}")
    if not args.no_pdf:
        print(f"PDFs -> {PRINT_DIR.relative_to(REPO_ROOT)}")
    print(f"Address verification required on {verify_count} of {len(rows)} custodians:")
    for r in rows:
        if CUSTODIANS.get(r["num"], {}).get("verify"):
            print(f"  - #{r['num']} {CUSTODIANS[r['num']]['name']}")
    if failures:
        print(f"\nFAILED ({len(failures)}): {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()