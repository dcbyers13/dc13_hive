#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Migrate LEGAL_FILE/ to new numbered structure.

Copies all files from the old LEGAL_FILE/ layout into a staging
directory (LEGAL_FILE_NEW/) with the 01-05, 99_MISC structure.
Does NOT delete the old structure — verify first, then swap.

Usage:
    uv run dc13_hive/scripts/migrate_legal_file.py [--dry-run]
"""

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import os
import sys
import shutil
from pathlib import Path

BASE = Path("/Users/macuser/LAW_LAB/25fa152/LEGAL_FILE")
STAGING = Path("/Users/macuser/LAW_LAB/25fa152/LEGAL_FILE_NEW")

LEGEND = """\
# LEGAL_FILE Organization Key

Numbered prefixes enforce stable IDE sorting under deadline pressure:

    01_DRAFTS/            Unfiled draft motions (Byers)
    02_ACTIVE_ORDERS/     Currently effective court orders (15FA152)
    03_BYERS_FILINGS/     Motions/exhibits filed by David Byers
    04_DONATELLO_FILINGS/ Answers/responses filed by Pauletta Donatello
    05_RELATED_CASES/     Prior/related cases, organized by case number
    99_MISC/              Misc docs (docket sheet, discovery, handover memo)

Party codes used in related-case folders:
    DCB = David Charles Byers (Petitioner)
    PDD = Pauletta D. Donatello (Respondent)
    CMN = Unknown jurisdiction (single case, filed separately)

Dual-format convention:
    Every document has both .pdf (original scan) and .md (text extract)
    companions. The .md files serve as the RAG-readable digital twin.

Migrated from legacy structure on 2026-06-01.
"""


def log(msg: str):
    print(f"  {msg}")


def copy_with_path(src: Path, dst: Path, dry_run: bool):
    """Copy a file, creating parent dirs if needed."""
    if dry_run:
        log(f"[dry-run] would copy: {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst)
        log(f"copied: {dst.relative_to(STAGING)}")
    except Exception as e:
        print(f"  ERROR copying {src.name}: {e}", file=sys.stderr)


def migrate(dry_run: bool):
    total = 0

    # ── 01_DRAFTS/ (from 0_DRAFTS/) ──
    log("01_DRAFTS/")
    src_dir = BASE / "0_DRAFTS"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "01_DRAFTS" / f.name, dry_run)
                total += 1

    # ── 02_ACTIVE_ORDERS/ (from ACTIVE_ORDERS/) ──
    log("02_ACTIVE_ORDERS/")
    src_dir = BASE / "ACTIVE_ORDERS"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "02_ACTIVE_ORDERS" / f.name, dry_run)
                total += 1

    # ── 03_BYERS_FILINGS/ (from FILED_MOTIONS_EXHIBITS_ETC/ root) ──
    log("03_BYERS_FILINGS/")
    src_dir = BASE / "FILED_MOTIONS_EXHIBITS_ETC"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "03_BYERS_FILINGS" / f.name, dry_run)
                total += 1

    # ── 04_DONATELLO_FILINGS/ (from FILED_MOTIONS_EXHIBITS_ETC/ANSWERS_RESPONSES/) ──
    log("04_DONATELLO_FILINGS/")
    src_dir = BASE / "FILED_MOTIONS_EXHIBITS_ETC" / "ANSWERS_RESPONSES"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "04_DONATELLO_FILINGS" / f.name, dry_run)
                total += 1

    # ── 05_RELATED_CASES/ ──

    # 14F318/ (from OLD_CASES/14F318-* and ARCHIVE/CIVIL/DCB/OP/15OP512*)
    log("05_RELATED_CASES/14F318/")
    src_dir = BASE / "FILED_MOTIONS_EXHIBITS_ETC" / "OLD_CASES"
    if src_dir.exists():
        for d in src_dir.iterdir():
            if d.is_dir() and "14F318" in d.name:
                for f in sorted(d.iterdir()):
                    if f.is_file() and f.name != ".DS_Store":
                        copy_with_path(f, STAGING / "05_RELATED_CASES" / "14F318" / f.name, dry_run)
                        total += 1
    # Add 15OP512 from archive (consolidated into 14F318)
    src_15op = BASE / "ARCHIVE" / "CIVIL" / "DCB" / "OP" / "15OP512_DOCKET_SHEET_4-21-2026.md"
    if src_15op.exists():
        copy_with_path(src_15op, STAGING / "05_RELATED_CASES" / "14F318" / "15OP512_DOCKET_SHEET_4-21-2026.md", dry_run)
        total += 1
    src_15op_pdf = src_15op.with_suffix(".pdf")
    if src_15op_pdf.exists():
        copy_with_path(src_15op_pdf, STAGING / "05_RELATED_CASES" / "14F318" / "15OP512_DOCKET_SHEET_4-21-2026.pdf", dry_run)
        total += 1

    # 13OP13/ (from ARCHIVE/CIVIL/DCB/OP/)
    log("05_RELATED_CASES/13OP13/")
    src_dir = BASE / "ARCHIVE" / "CIVIL" / "DCB" / "OP"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and "13OP13" in f.name and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "05_RELATED_CASES" / "13OP13" / f.name, dry_run)
                total += 1

    # 22OP713/ (from ARCHIVE/CIVIL/PDD/OP/)
    log("05_RELATED_CASES/22OP713/")
    src_dir = BASE / "ARCHIVE" / "CIVIL" / "PDD" / "OP"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "05_RELATED_CASES" / "22OP713" / f.name, dry_run)
                total += 1

    # 24OP613/ (from OLD_CASES/24OP613-* and ARCHIVE/CIVIL/DCB/OP/24OP613*)
    log("05_RELATED_CASES/24OP613/")
    src_dir = BASE / "FILED_MOTIONS_EXHIBITS_ETC" / "OLD_CASES"
    if src_dir.exists():
        for d in src_dir.iterdir():
            if d.is_dir() and "24OP613" in d.name:
                for f in sorted(d.iterdir()):
                    if f.is_file() and f.name != ".DS_Store":
                        copy_with_path(f, STAGING / "05_RELATED_CASES" / "24OP613" / f.name, dry_run)
                        total += 1
    # Add 24OP613 court file from archive
    src_dir_arch = BASE / "ARCHIVE" / "CIVIL" / "DCB" / "OP"
    if src_dir_arch.exists():
        for f in sorted(src_dir_arch.iterdir()):
            if f.is_file() and "24OP613" in f.name and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "05_RELATED_CASES" / "24OP613" / f.name, dry_run)
                total += 1

    # DCB_CRIMINAL/ (David's criminal history from ARCHIVE/CRIMINAL/DCB/)
    log("05_RELATED_CASES/DCB_CRIMINAL/")
    src_dir = BASE / "ARCHIVE" / "CRIMINAL" / "DCB"
    if src_dir.exists():
        for root, dirs, files in os.walk(src_dir):
            for fname in files:
                if fname == ".DS_Store":
                    continue
                src = Path(root) / fname
                rel = src.relative_to(src_dir)
                dst = STAGING / "05_RELATED_CASES" / "DCB_CRIMINAL" / rel
                copy_with_path(src, dst, dry_run)
                total += 1

    # PDD_CRIMINAL/ (Pauletta's criminal history from ARCHIVE/CRIMINAL/PDD/)
    log("05_RELATED_CASES/PDD_CRIMINAL/")
    src_dir = BASE / "ARCHIVE" / "CRIMINAL" / "PDD"
    if src_dir.exists():
        for root, dirs, files in os.walk(src_dir):
            for fname in files:
                if fname == ".DS_Store":
                    continue
                src = Path(root) / fname
                rel = src.relative_to(src_dir)
                dst = STAGING / "05_RELATED_CASES" / "PDD_CRIMINAL" / rel
                copy_with_path(src, dst, dry_run)
                total += 1

    # CMN_18CM2996/ (single case, from ARCHIVE/CRIMINAL/CMN/)
    log("05_RELATED_CASES/CMN_18CM2996/")
    src_dir = BASE / "ARCHIVE" / "CRIMINAL" / "CMN"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.name != ".DS_Store":
                copy_with_path(f, STAGING / "05_RELATED_CASES" / "CMN_18CM2996" / f.name, dry_run)
                total += 1

    # ── 99_MISC/ (root-level LEGAL_FILE orphans) ──
    log("99_MISC/")
    root_files = [
        ("2026_06_01-25FA152_DOCKET_SHEET.pdf", None),
        ("2501048_Redacted-KALEB.pdf", None),
        ("CASE_HANDOVER_MEMO.md", None),
        ("CASE_HANDOVER_MEMO.pdf", None),
        ("PDF7247.PDF - PDF7247.pdf", "PDF7247.pdf"),  # sanitize
    ]
    for fname, rename in root_files:
        src = BASE / fname
        if src.exists():
            dst_name = rename if rename else fname
            copy_with_path(src, STAGING / "99_MISC" / dst_name, dry_run)
            total += 1

    # ── Write 00_README.md ──
    if not dry_run:
        readme_path = STAGING / "00_README.md"
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text(LEGEND, encoding="utf-8")
        log("wrote: LEGAL_FILE_NEW/00_README.md")

    print(f"\n{'─'*50}")
    if dry_run:
        print(f"Dry-run complete. Would copy {total} files.")
    else:
        print(f"Migration complete. Copied {total} files to {STAGING}")
        print("Verify the new structure before swapping:")
        print("  mv LEGAL_FILE LEGAL_FILE_OLD && mv LEGAL_FILE_NEW LEGAL_FILE")
    return total


def main():
    dry_run = "--dry-run" in sys.argv

    if not BASE.exists():
        print(f"Error: source directory not found: {BASE}", file=sys.stderr)
        sys.exit(1)

    if STAGING.exists() and not dry_run:
        print(f"Error: staging directory already exists: {STAGING}", file=sys.stderr)
        print("Remove it first: rm -rf 25fa152/LEGAL_FILE_NEW")
        sys.exit(1)

    print(f"Source:   {BASE}")
    print(f"Staging:  {STAGING}")
    print(f"Dry run:  {dry_run}")
    print()

    count = migrate(dry_run)
    print(f"\nTotal: {count} files processed")


if __name__ == "__main__":
    main()
