#!/usr/bin/env python3
"""
Assemble the two Master Trial Binders for the November 10, 2026 Consolidated Hearing
(Case No. 25FA152 / Consolidated with 26OP158, Room 330, Hon. Sarah Gallagher-Chami):

1. 01_DAVID_COCKPIT_WORKING_BINDER_1x_SINGLE_SIDED.pdf
   - David's personal trial cockpit binder (shields, bench card, motions, opening,
     verbatim cross-examinations, direct examinations, testimony shield, and closing).
2. 02_OFFICIAL_EXHIBITS_TABS_A_J_3x_DOUBLE_SIDED.pdf
   - Complete 10-Tab Trial Exhibit Binder (Master Index + Tabs A through J with
     dynamically generated ReportLab Tab separator pages).
3. PRINT_SHOP_WORK_ORDER.txt
   - Exact page counts, tab page locations, and printing/binding instructions for
     Indian Grocery Store and Copy.

Usage:
    uv run dc13_hive/scripts/build_nov10_binders.py
    python3 dc13_hive/scripts/build_nov10_binders.py
"""

# /// script
# dependencies = ["pypdf", "reportlab"]
# ///

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Union

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas


REPO_ROOT = Path(__file__).resolve().parents[2]
BINDERS_DIR = REPO_ROOT / "25FA152" / "PRINT" / "NOV_10" / "BINDERS"


def create_tab_page(tab_letter: str, tab_title: str, subtitle: str = "") -> io.BytesIO:
    """
    Generate a clean, bold 1-page Letter PDF divider sheet in memory using ReportLab.
    - 24pt Bold: TAB {tab_letter} (or {tab_letter} if already prefixed with TAB/FRONT)
    - 16pt Bold: {tab_title}
    - 12pt Italic: {subtitle}
    """
    buf = io.BytesIO()
    width, height = letter
    c = canvas.Canvas(buf, pagesize=letter)

    # Outer frame & accent bar
    margin = 48
    c.setStrokeColor(colors.HexColor("#1a2a40"))
    c.setLineWidth(2.0)
    c.rect(margin, margin, width - 2 * margin, height - 2 * margin, stroke=1, fill=0)

    c.setStrokeColor(colors.HexColor("#cfd6de"))
    c.setLineWidth(0.75)
    c.rect(
        margin + 6,
        margin + 6,
        width - 2 * (margin + 6),
        height - 2 * (margin + 6),
        stroke=1,
        fill=0,
    )

    # Case caption header at top of divider
    c.setFillColor(colors.HexColor("#4a5568"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(
        width / 2,
        height - margin - 28,
        "IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL CIRCUIT — DEKALB COUNTY, ILLINOIS",
    )
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(
        width / 2,
        height - margin - 42,
        "Byers v. Donatello | Case No. 25FA152 (Consolidated with 26OP158) | Room 330 | Hon. Sarah Gallagher-Chami",
    )

    # Normalize tab heading
    clean_tab = tab_letter.strip().upper()
    if not clean_tab.startswith("TAB") and clean_tab != "FRONT":
        header_text = f"TAB {clean_tab}"
    else:
        header_text = clean_tab

    center_y = height * 0.56

    # 24pt Bold Tab Identifier
    c.setFillColor(colors.HexColor("#1a2a40"))
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, center_y + 42, header_text)

    # Horizontal divider line under Tab label
    c.setStrokeColor(colors.HexColor("#1a2a40"))
    c.setLineWidth(1.5)
    c.line(width * 0.25, center_y + 24, width * 0.75, center_y + 24)

    # 16pt Bold Title (wrapped safely within margins)
    max_text_width = width - 2 * (margin + 36)
    c.setFont("Helvetica-Bold", 16)
    title_lines = simpleSplit(tab_title.strip(), "Helvetica-Bold", 16, max_text_width)
    y_cursor = center_y - 4
    for line in title_lines:
        c.drawCentredString(width / 2, y_cursor, line)
        y_cursor -= 22

    # 12pt Italic Subtitle (wrapped safely within margins)
    if subtitle:
        y_cursor -= 6
        c.setFillColor(colors.HexColor("#2d3748"))
        c.setFont("Helvetica-Oblique", 12)
        sub_lines = simpleSplit(subtitle.strip(), "Helvetica-Oblique", 12, max_text_width)
        for line in sub_lines:
            c.drawCentredString(width / 2, y_cursor, line)
            y_cursor -= 17

    # Footer
    c.setFillColor(colors.HexColor("#718096"))
    c.setFont("Helvetica", 8)
    c.drawCentredString(
        width / 2,
        margin + 20,
        "Consolidated Trial Hearing — Tuesday, November 10, 2026 at 1:30 PM",
    )

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def resolve_pdf_path(candidates: Union[str, List[str]]) -> Optional[Path]:
    """Resolve the first existing PDF path from a candidate or list of candidate relative paths."""
    if isinstance(candidates, str):
        candidates = [candidates]
    for rel in candidates:
        p = Path(rel)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.exists() and p.is_file():
            return p
    return None


def build_binder(
    binder_name: str,
    output_filename: str,
    items: List[dict],
) -> Tuple[Path, int, List[dict]]:
    """
    Assemble a master binder PDF from a list of tab dividers and document specs.
    Returns (output_path, total_pages, manifest_rows).
    """
    BINDERS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = BINDERS_DIR / output_filename
    writer = PdfWriter()
    manifest: List[dict] = []
    current_page = 1

    print("=" * 78)
    print(f"BUILDING: {binder_name}")
    print(f"TARGET:   {output_path.relative_to(REPO_ROOT)}")
    print("=" * 78)

    for item in items:
        kind = item["type"]
        if kind == "tab":
            tab_letter = item["tab_letter"]
            tab_title = item["tab_title"]
            subtitle = item.get("subtitle", "")
            tab_buf = create_tab_page(tab_letter, tab_title, subtitle)
            reader = PdfReader(tab_buf)
            num_pages = len(reader.pages)
            for page in reader.pages:
                writer.add_page(page)
            label = f"[DIVIDER] {tab_letter}: {tab_title}"
            print(f"  + {label:<58} (p. {current_page:>3}, {num_pages:>3}p)")
            manifest.append(
                {
                    "kind": "DIVIDER",
                    "label": f"{tab_letter} — {tab_title}",
                    "subtitle": subtitle,
                    "path": "Generated ReportLab Divider",
                    "start_page": current_page,
                    "end_page": current_page + num_pages - 1,
                    "pages": num_pages,
                }
            )
            current_page += num_pages

        elif kind == "pdf":
            candidates = item["paths"]
            label = item.get("label", "")
            resolved = resolve_pdf_path(candidates)
            if resolved is None:
                cand_str = ", ".join(candidates) if isinstance(candidates, list) else str(candidates)
                print(f"  ! WARNING: MISSING FILE -> {cand_str}", file=sys.stderr)
                manifest.append(
                    {
                        "kind": "MISSING",
                        "label": label or cand_str,
                        "subtitle": "",
                        "path": cand_str,
                        "start_page": current_page,
                        "end_page": current_page,
                        "pages": 0,
                    }
                )
                continue

            reader = PdfReader(str(resolved))
            num_pages = len(reader.pages)
            for page in reader.pages:
                writer.add_page(page)

            rel_str = str(resolved.relative_to(REPO_ROOT))
            display_label = label or resolved.name
            print(
                f"  + {display_label:<58} (pp. {current_page:>3}-{current_page + num_pages - 1:>3}, {num_pages:>3}p) [{rel_str}]"
            )
            manifest.append(
                {
                    "kind": "DOCUMENT",
                    "label": display_label,
                    "subtitle": "",
                    "path": rel_str,
                    "start_page": current_page,
                    "end_page": current_page + num_pages - 1,
                    "pages": num_pages,
                }
            )
            current_page += num_pages

    total_pages = current_page - 1
    with open(output_path, "wb") as f:
        writer.write(f)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print("-" * 78)
    print(f"COMPLETED: {output_path.name} | Total Pages: {total_pages} | Size: {size_mb:.2f} MB")
    print()
    return output_path, total_pages, manifest


def build_dividers_only_pdf(
    items: List[dict],
    output_filename: str = "OFFICIAL_EXHIBITS_TABS_A_J_DIVIDERS_ONLY.pdf",
) -> Path:
    """Generate a clean 10-page standalone PDF containing only the Tab Title Divider pages."""
    BINDERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BINDERS_DIR / output_filename
    writer = PdfWriter()
    for item in items:
        if item.get("type") == "tab":
            tab_letter = item["tab_letter"]
            tab_title = item["tab_title"]
            subtitle = item.get("subtitle", "")
            tab_buf = create_tab_page(tab_letter, tab_title, subtitle)
            reader = PdfReader(tab_buf)
            for page in reader.pages:
                writer.add_page(page)

    with open(out_path, "wb") as f:
        writer.write(f)

    size_kb = out_path.stat().st_size / 1024
    print(f"COMPLETED: {out_path.name} | Total Pages: {len(writer.pages)} | Size: {size_kb:.1f} KB")
    print()
    return out_path


def write_work_order(
    binder1_path: Path,
    binder1_pages: int,
    binder1_manifest: List[dict],
    binder2_path: Path,
    binder2_pages: int,
    binder2_manifest: List[dict],
) -> Path:
    """Write PRINT_SHOP_WORK_ORDER.txt with clear instructions for the print shop clerk."""
    work_order_path = BINDERS_DIR / "PRINT_SHOP_WORK_ORDER.txt"

    b1_dividers = [m for m in binder1_manifest if m["kind"] == "DIVIDER"]
    b2_dividers = [m for m in binder2_manifest if m["kind"] == "DIVIDER"]

    lines = [
        "================================================================================",
        "PRINT SHOP WORK ORDER — INDIAN GROCERY STORE AND COPY",
        "Customer: David C. Byers (Phone: 779-400-9307 / 815-322-1013)",
        "Hearing:  Tuesday, November 10, 2026 at 1:30 PM (DeKalb County Courthouse, Rm 330)",
        "================================================================================",
        "",
        "OVERVIEW OF PRINT JOB (2 MASTER PDF FILES IN THIS FOLDER):",
        "--------------------------------------------------------------------------------",
        f"FILE 1: {binder1_path.name}",
        f"  • Total PDF Pages:   {binder1_pages} pages",
        "  • Quantity:          1 COPY ONLY (for Petitioner's Podium Binder)",
        "  • Print Mode:        SINGLE-SIDED (1-Sided) on standard 8.5\" x 11\" white paper",
        "  • Finishing:         Standard 3-Hole Punch on left edge",
        "  • Divider Sheets:    Print the 8 [DIVIDER] pages on Heavy Cardstock / Colored",
        "                       Index Stock (or insert 8-Tab Avery Binder Dividers at the",
        "                       exact PDF page numbers listed below).",
        "",
        f"FILE 2: {binder2_path.name}",
        f"  • Total PDF Pages:   {binder2_pages} pages per set ({binder2_pages * 3} pages total across 3 sets)",
        "  • Quantity:          3 IDENTICAL SETS (Set 1: Judge | Set 2: Opposing/GAL | Set 3: Witness/Petitioner)",
        "  • Print Mode:        DOUBLE-SIDED (2-Sided, Flip on Long Edge) on 8.5\" x 11\" white paper",
        "  • Finishing:         Standard 3-Hole Punch on left edge",
        "  • Divider Sheets:    Insert 10-Tab Lettered Index Dividers (TABS A through J)",
        "                       at the exact PDF page numbers listed below.",
        "                       (OPTIONAL DEDICATED DIVIDER FILE: OFFICIAL_EXHIBITS_TABS_A_J_DIVIDERS_ONLY.pdf",
        "                       contains just these 10 tab pages for cardstock/tab printing).",
        "",
        "================================================================================",
        f"DETAILED MANIFEST — FILE 1: {binder1_path.name}",
        f"(1 Copy • Single-Sided • {binder1_pages} Total Pages • 3-Hole Punched)",
        "================================================================================",
        f"{'PDF Pages':<14} {'Len':<6} {'Type':<10} {'Section / Document Description'}",
        "-" * 80,
    ]

    for m in binder1_manifest:
        pg_range = (
            f"p. {m['start_page']}"
            if m["start_page"] == m["end_page"]
            else f"pp. {m['start_page']}-{m['end_page']}"
        )
        lines.append(f"{pg_range:<14} {m['pages']:>3}p   {m['kind']:<10} {m['label']}")

    lines.extend(
        [
            "",
            "FILE 1 TAB DIVIDER PAGE NUMBERS (FOR CARDSTOCK OR PHYSICAL TABS):",
        ]
    )
    for d in b1_dividers:
        lines.append(f"  - PDF Page {d['start_page']:>3}: {d['label']}")

    lines.extend(
        [
            "",
            "================================================================================",
            f"DETAILED MANIFEST — FILE 2: {binder2_path.name}",
            f"(3 Identical Copies • Double-Sided • {binder2_pages} Pages/Set • Tabs A through J)",
            "================================================================================",
            f"{'PDF Pages':<14} {'Len':<6} {'Type':<10} {'Tab / Exhibit Description'}",
            "-" * 80,
        ]
    )

    for m in binder2_manifest:
        pg_range = (
            f"p. {m['start_page']}"
            if m["start_page"] == m["end_page"]
            else f"pp. {m['start_page']}-{m['end_page']}"
        )
        lines.append(f"{pg_range:<14} {m['pages']:>3}p   {m['kind']:<10} {m['label']}")

    lines.extend(
        [
            "",
            "FILE 2 OFFICIAL EXHIBIT TAB DIVIDER PAGE NUMBERS (TABS A THROUGH J):",
        ]
    )
    for d in b2_dividers:
        lines.append(f"  - PDF Page {d['start_page']:>3}: {d['label']}")

    lines.extend(
        [
            "",
            "================================================================================",
            "CLERK CHECKLIST BEFORE HANDOFF:",
            "  [ ] File 1 printed 1x SINGLE-SIDED, 3-hole punched, tabs at FRONT & TABS 1-7.",
            "  [ ] File 2 printed 3x DOUBLE-SIDED, 3-hole punched, lettered TABS A-J inserted.",
            "  [ ] Pages 1-4 of File 1 (Pocket Shield & Trial Bench Card) verified legible.",
            "================================================================================",
            "",
        ]
    )

    work_order_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE WORK ORDER: {work_order_path.relative_to(REPO_ROOT)}")
    return work_order_path


def main() -> int:
    # -------------------------------------------------------------------------
    # BINDER 1: DAVID'S COCKPIT WORKING BINDER (1x SINGLE-SIDED)
    # -------------------------------------------------------------------------
    binder1_items = [
        {
            "type": "tab",
            "tab_letter": "FRONT",
            "tab_title": "QUICK REFERENCE SHIELDS",
            "subtitle": "Podium Cheat Sheets & Objections Card",
        },
        {
            "type": "pdf",
            "label": "Testimony & Cross-Defense Pocket Shield (2p)",
            "paths": [
                "25FA152/PRINT/NOV_10/05_BENCH_STATEMENTS/TESTIMONY_CROSS_DEFENSE_POCKET_SHIELD.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Trial Bench Card: Objections & Record Preservation (2p)",
            "paths": [
                "25FA152/PRINT/NOV_10/05_BENCH_STATEMENTS/TRIAL_BENCH_CARD_OBJECTIONS_AND_RECORD_PRESERVATION.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 1",
            "tab_title": "PRE-TRIAL MOTIONS",
            "subtitle": "Rule 216 Deemed Admissions, Stephanie Johnson Video Testimony & ADA Accommodation",
        },
        {
            "type": "pdf",
            "label": "Motion to Deem Facts Admitted Pursuant to Rule 216(c)",
            "paths": [
                "25FA152/PRINT/NOV_10/01_MOTIONS/MOTION_TO_DEEM_FACTS_ADMITTED_RULE_216.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Motion for Remote Video Testimony — Stephanie Johnson, LCSW",
            "paths": [
                "25FA152/PRINT/NOV_10/MOTION_FOR_VIDEO_TESTIMONY_STEPHANIE_JOHNSON.pdf",
                "25FA152/NOV_10/MOTION_FOR_VIDEO_TESTIMONY_STEPHANIE_JOHNSON.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "ADA Accommodation Request & Order (FND / C-PTSD Safety Net)",
            "paths": [
                "25FA152/LEGAL_FILE/03_BYERS_FILINGS/2026_05_07_Request_for_Accommodation_ADA.pdf",
                "25FA152/OCR_BATCH/2026_05_07_Request_for_Accommodation_ADA.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 2",
            "tab_title": "OPENING STATEMENT",
            "subtitle": "Bench Opening Script under ADA Order",
        },
        {
            "type": "pdf",
            "label": "Bench Opening Statement (Nov. 10, 2026)",
            "paths": [
                "25FA152/PRINT/NOV_10/05_BENCH_STATEMENTS/BENCH_OPENING_STATEMENT.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 3",
            "tab_title": "CROSS-EXAMINATION: MOTHER",
            "subtitle": "Adverse Examination under 735 ILCS 5/2-1102 & Rule 216 Impeachment",
        },
        {
            "type": "pdf",
            "label": "Verbatim Cross-Examination — Pauletta D. Donatello (Phases 1-8)",
            "paths": [
                "25FA152/PRINT/NOV_10/03_CROSS_EXAMINATION/VERBATIM_CROSS_PAULETTA_DONATELLO.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 4",
            "tab_title": "CROSS-EXAMINATION: GAL",
            "subtitle": "Adverse Examination under 750 ILCS 5/506(a)(2) & Certified Transcript Impeachment",
        },
        {
            "type": "pdf",
            "label": "Verbatim Cross-Examination — GAL Evan King (Traps 1-5)",
            "paths": [
                "25FA152/PRINT/NOV_10/03_CROSS_EXAMINATION/VERBATIM_CROSS_EVAN_KING.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 5",
            "tab_title": "DIRECT EXAMINATIONS",
            "subtitle": "Steve Byers & Stephanie Johnson, LCSW",
        },
        {
            "type": "pdf",
            "label": "Direct Examination — Theresa Callahan & Steve Byers",
            "paths": [
                "25FA152/PRINT/NOV_10/03_DIRECT_EXAMINATION/DIRECT_EXAMINATION_TERRI_AND_STEVE_BYERS.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Direct Examination — Stephanie Johnson, LCSW (Rule 213(f)(2))",
            "paths": [
                "25FA152/PRINT/NOV_10/03_DIRECT_EXAMINATION/DIRECT_EXAMINATION_STEPHANIE_JOHNSON.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 6",
            "tab_title": "PETITIONER TESTIMONY & SHIELD",
            "subtitle": "Self-Directed Narrative & Cross-Defense Vectors",
        },
        {
            "type": "pdf",
            "label": "Petitioner Testimony & Cross-Defense Shield",
            "paths": [
                "25FA152/PRINT/NOV_10/03_DIRECT_EXAMINATION/PETITIONER_TESTIMONY_AND_CROSS_DEFENSE.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB 7",
            "tab_title": "CLOSING ARGUMENT & RELIEF",
            "subtitle": "Statutory Argument under 750 ILCS 5/610.5 & 602.5",
        },
        {
            "type": "pdf",
            "label": "Memorandum in Support of Precursor Dismissal & 750 ILCS 5/604.10(b)",
            "paths": [
                "25FA152/PRINT/NOV_10/01_MOTIONS/MEMORANDUM_IN_SUPPORT_OF_PRECURSOR_DISMISSAL_AND_604.10B.pdf",
            ],
        },
    ]

    # -------------------------------------------------------------------------
    # BINDER 2: OFFICIAL TRIAL EXHIBITS — TABS A THROUGH J (3x DOUBLE-SIDED)
    # -------------------------------------------------------------------------
    binder2_items = [
        {
            "type": "pdf",
            "label": "Official Trial Exhibit Master Index (Tabs A through J)",
            "paths": [
                "25FA152/PRINT/NOV_10/04_EXHIBITS/NOV_10_EXHIBIT_MASTER_INDEX.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB A",
            "tab_title": "ALLOCATION JUDGMENT",
            "subtitle": "August 3, 2022 Judgment (Kane County Case No. 14F318)",
        },
        {
            "type": "pdf",
            "label": "Tab A: August 3, 2022 Allocation Judgment (14F318)",
            "paths": [
                "25FA152/LEGAL_FILE/02_ACTIVE_ORDERS/2022-08-03_ALLOCATION_JUDGMENT.pdf",
                "GUIDING_LIGHTS/2022-08-03_ALLOCATION_JUDGMENT.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB B",
            "tab_title": "CENTERPOINTE HOSPITAL RECORDS",
            "subtitle": "Executed ROI Release, Official Transmittal Email & Certified 134-Page Inpatient Record",
        },
        {
            "type": "pdf",
            "label": "Tab B-1: Executed CenterPointe Hospital ROI Release Form (July 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/CENTERPOINTE_ROI_FORM_SIGNED_07_2026.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab B-2: CenterPointe HIM Department Official Transmittal Email Thread (July 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab B-3: CenterPointe Hospital Certified Inpatient ROI (134 pp., July 8-23, 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_HOSPITAL_MO_07_2026.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB C",
            "tab_title": "DEKALB CUSD #428 SCHOOL RECORDS",
            "subtitle": "Hodges Loizzi Letter, GAL Subpoena Refusal & Skyward Q2 Science Progress Report",
        },
        {
            "type": "pdf",
            "label": "Tab C-1: Hodges Loizzi / Kerry B. Pipal Letter (Oct. 26, 2026, Doc #3057383.1)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_A_CUSD_428_HODGES_LOIZZI_SUBPOENA_RESPONSE.pdf",
                "25FA152/PRINT/NOV_10/OCT_29/EXHIBIT_A_CUSD_428_HODGES_LOIZZI_SUBPOENA_RESPONSE.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/SCHOOL_RECORDS/2026_10_26_CUSD_428_HODGES_LOIZZI_SUBPOENA_RESPONSE.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab C-2: GAL Evan King Written Subpoena Refusal Thread (Oct. 26, 2026)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_B_GAL_DEMAND_AND_REFUSAL_CUSD_428_RECORDS_THREAD.pdf",
                "25FA152/PRINT/NOV_10/OCT_29/EXHIBIT_B_GAL_DEMAND_AND_REFUSAL_CUSD_428_RECORDS_THREAD.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/GAL_DOCS/2026_10_26_GAL_DEMAND_AND_REFUSAL_CUSD_428_RECORDS_THREAD.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab C-3: Skyward Q2 8th-Grade Science Progress Report (Todd Hallaron, Nov. 3, 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/SCHOOL_RECORDS/2026_11_03_SKYWARD_Q2_PROGRESS_REPORT.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB D",
            "tab_title": "RULE 216 ADMISSIONS PACKET",
            "subtitle": "Requests for Admission, Proofs of Service & Untimely Sworn Responses",
        },
        {
            "type": "pdf",
            "label": "Tab D-1: Petitioner's Rule 216 Requests for Admission to Mother (Sept. 10, 2026)",
            "paths": [
                "25FA152/PRINT/NOV_10/02_DISCOVERY/RULE_216_REQUESTS_FOR_ADMISSION_MOTHER.pdf",
                "25FA152/PRINT/NOV_10/IN_CUSTODY_SERVICE/FILESTAMPED/04_RULE_216_REQUESTS_FOR_ADMISSION_MOTHER.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab D-2: Odyssey eFileIL Filing Acceptance Receipt (Envelope #39932362, Sept. 10, 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/03_BYERS_FILINGS/2026_09_10_RULE_216_SERVICE_ACCEPTANCE_ENV_39932362.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab D-3: Respondent's Untimely Sworn Rule 216 Responses (Filed Oct. 15, 2026)",
            "paths": [
                "25FA152/PRINT/NOV_10/02_DISCOVERY/RESPONDENT_RULE_216_RESPONSES.pdf",
                "25FA152/NOV_10/02_DISCOVERY/RESPONDENT_RULE_216_RESPONSES.pdf",
                "25FA152/LEGAL_FILE/04_DONATELLO_FILINGS/2026_10_15_RESPONDENT_RULE_216_RESPONSES.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab D-4: Odyssey eFileIL Notification of Service (Envelope #40486439, Oct. 15, 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/04_DONATELLO_FILINGS/2026_10_15_RULE_216_SERVICE_NOTIFICATION_ENV_40486439.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB E",
            "tab_title": "SEPTEMBER 3, 2026 TRANSCRIPT",
            "subtitle": "Certified Report of Proceedings (Official Court Reporter Sandra Foord)",
        },
        {
            "type": "pdf",
            "label": "Tab E: Certified Report of Proceedings (Sept. 3, 2026, CSR Sandra Foord)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/GAL_DOCS/2026_09_03_REPORT_OF_PROCEEDINGS_TRANSCRIPT.pdf",
                "25FA152/NOV_10/OCT_29/EXHIBIT_H_CERTIFIED_SEPT_3_2026_TRANSCRIPT_AND_FOORD_EMAIL.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB F",
            "tab_title": "MIND MATTERS CLINICAL PROTOCOL",
            "subtitle": "Annie Barsch, LMFT Reunification Therapy Protocol & Correspondence",
        },
        {
            "type": "pdf",
            "label": "Tab F-1: Mind Matters / Annie Barsch, LMFT Subpoena Release Email (Oct. 27, 2026)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_E_MIND_MATTERS_ANNIE_BARSCH_RELEASE_EMAIL.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/2026_10_27_MIND_MATTERS_ANNIE_BARSCH_RELEASE_EMAIL.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab F-2: Mind Matters 3-Step Reunification Therapy Protocol",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/COMMUNICATION/MIND_MATTERS_PROTOCOL.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB G",
            "tab_title": "PATERNAL RESIDENTIAL STABILITY",
            "subtitle": "5-Year Lease, HUD Voucher, Grandma Terri Letter & Short-Term Guardianship Appointment",
        },
        {
            "type": "pdf",
            "label": "Tab G-1: Paternal Residential Stability Packet (5-Year Lease, HUD Voucher, RFTA, Inspection)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/RESIDENTIAL_STABILITY/EXHIBIT_G.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/HOUSING_HISTORY/2021_10_15_lease.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab G-2: Signed Statement of Paternal Grandmother Theresa Callahan (Exhibit TC, Dec. 26, 2024)",
            "paths": [
                "25FA152/LEGAL_FILE/05_RELATED_CASES/24OP613/2024_12_26_EXHIBIT_TC_SIGNED_LETTER.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab G-3: Short-Term Guardianship Appointment Executed by Respondent (Aug. 9, 2026, 755 ILCS 5/11-5.4)",
            "paths": [
                "25FA152/LEGAL_FILE/05_RELATED_CASES/26OP158/2026_08_09_SHORT_TERM_GUARDIAN_APPOINTMENT.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB H",
            "tab_title": "26CM392 DISMISSAL ORDER",
            "subtitle": "Certified Order of Dismissal in the Interest of Justice (Judge Marcy Buick, Sept 9, 2026)",
        },
        {
            "type": "pdf",
            "label": "Tab H: Certified Dismissal Order in People v. David Byers (Case No. 26CM392, Sept. 9, 2026)",
            "paths": [
                "25FA152/LEGAL_FILE/05_RELATED_CASES/26CM392/2026_09_09_ORDER_DISMISSAL_26CM392.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB I",
            "tab_title": "OUTPATIENT & CLINICAL RECORDS",
            "subtitle": "Daybreak Health, Streamwood, Ellie Mental Health & BGC Closure Letter",
        },
        {
            "type": "pdf",
            "label": "Tab I-1: Daybreak Health Clinical Director Written Advisement (Christine Cauwels, Oct. 27, 2026)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_F_DAYBREAK_HEALTH_CAUWELS_RESPONSE.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/2026_10_27_DAYBREAK_HEALTH_CAUWELS_RESPONSE.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab I-2: Streamwood Behavioral Healthcare Subpoena Response (Katarzyna Michalik, Oct. 26, 2026)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_C_STREAMWOOD_MICHALIK_SUBPOENA_RESPONSE.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/2026_10_26_STREAMWOOD_MICHALIK_SUBPOENA_RESPONSE.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab I-3: Ellie Mental Health Subpoena Response (Dana Pavlu, LCSW, Oct. 26, 2026)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_D_ELLIE_MENTAL_HEALTH_PAVLU_SUBPOENA_RESPONSE.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/2026_10_26_ELLIE_MENTAL_HEALTH_PAVLU_SUBPOENA_RESPONSE.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab I-4: Ben Gordon Center / Northwestern Medicine File Closure Letter (Oct. 27, 2025)",
            "paths": [
                "25FA152/LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/2025_10_27_BGC_CLOSURE_LETTER_DONATELLO.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_FILE_CLOSURE_LETTER_10_2025.pdf",
            ],
        },
        {
            "type": "tab",
            "tab_letter": "TAB J",
            "tab_title": "PROCEDURAL DILIGENCE LEDGER",
            "subtitle": "Paternal 28-Filing Ledger & GAL Invoice #4545 Zero-Hour Audit",
        },
        {
            "type": "pdf",
            "label": "Tab J-1: Paternal Procedural Diligence Ledger (28 Pro Se Filings, Aug. 2025 - Aug. 2026)",
            "paths": [
                "25FA152/PRINT/NOV_10/04_EXHIBITS/EXHIBIT_PATERNAL_PROCEDURAL_DILIGENCE_28_FILINGS.pdf",
            ],
        },
        {
            "type": "pdf",
            "label": "Tab J-2: GAL Evan King Invoice #4545 (Oct. 1, 2026 — 0.00 Hours Follow-Up Audit)",
            "paths": [
                "25FA152/NOV_10/OCT_29/EXHIBIT_I_GAL_INVOICE_4545.pdf",
                "25FA152/LEGAL_FILE/02_EXHIBITS/GAL_DOCS/2026_10_01_GAL_INVOICE_4545.pdf",
            ],
        },
    ]

    b1_path, b1_pages, b1_manifest = build_binder(
        binder_name="Binder 1 — David's Cockpit Working Binder (1x Single-Sided)",
        output_filename="01_DAVID_COCKPIT_WORKING_BINDER_1x_SINGLE_SIDED.pdf",
        items=binder1_items,
    )

    b2_path, b2_pages, b2_manifest = build_binder(
        binder_name="Binder 2 — Official Trial Exhibits Tabs A–J (3x Double-Sided)",
        output_filename="02_OFFICIAL_EXHIBITS_TABS_A_J_3x_DOUBLE_SIDED.pdf",
        items=binder2_items,
    )

    build_dividers_only_pdf(binder2_items)

    write_work_order(b1_path, b1_pages, b1_manifest, b2_path, b2_pages, b2_manifest)

    missing = [
        m for m in (b1_manifest + b2_manifest) if m["kind"] == "MISSING"
    ]
    if missing:
        print(f"ERROR: {len(missing)} document(s) could not be resolved!", file=sys.stderr)
        return 1

    print("ALL MASTER BINDERS AND WORK ORDER GENERATED WITH ZERO MISSING FILES.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
