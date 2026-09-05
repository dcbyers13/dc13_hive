#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Batch-compile all active NOV_10 hearing markdown into court-ready PDFs.

Mirrors the 25FA152/NOV_10/ subfolder hierarchy inside 25FA152/PRINT/NOV_10/ and
compiles every target .md into a same-name .pdf by invoking motion_to_pdf.py
with the Petitioner's established 0.72" margin style.

Excluded internal trackers (never printed):
  - MASTER_PREP_TRACKER.md
  - MEDICAL_RECORD_AUDIT.md
  - SUBPOENA_DUCES_TECUM_INDEX.md

Usage:
    uv run dc13_hive/scripts/sync_nov10_print.py            # full run, compile all
    uv run dc13_hive/scripts/sync_nov10_print.py --dry-run   # list targets, compile nothing
    uv run dc13_hive/scripts/sync_nov10_print.py --force     # re-render even if PDF is newer than .md
"""

import os
import subprocess
import sys
from pathlib import Path

SOURCE_ROOT = Path("25FA152/NOV_10")
TARGET_ROOT = Path("25FA152/PRINT/NOV_10")

# Allowed subdirectories under SOURCE_ROOT (Tracker/exhibit-only dirs excluded)
INCLUDE_DIRS = [
    "01_MOTIONS",
    "02_DISCOVERY",
    "03_CROSS_EXAMINATION",
    "03_DIRECT_EXAMINATION",
    "05_BENCH_STATEMENTS",
]

# Internal trackers / management docs never compiled to PDF
EXCLUDE_FILES = {
    "MASTER_PREP_TRACKER.md",
    "MEDICAL_RECORD_AUDIT.md",
    "SUBPOENA_DUCES_TECUM_INDEX.md",
}

MARGIN = "0.72"
MOTION_TO_PDF = Path("dc13_hive/scripts/motion_to_pdf.py")
STYLESHEET_FLAG = "--margin"


def discover_targets():
    """Return list of (source_md, target_pdf) tuples for all eligible files."""
    targets = []
    for sub in INCLUDE_DIRS:
        srcdir = SOURCE_ROOT / sub
        if not srcdir.is_dir():
            continue
        for md in sorted(srcdir.rglob("*.md")):
            if md.name in EXCLUDE_FILES:
                continue
            rel = md.relative_to(SOURCE_ROOT)
            target_pdf = TARGET_ROOT / rel.with_suffix(".pdf")
            targets.append((md, target_pdf))
    return targets


def needs_render(source_md, target_pdf):
    """True if the PDF is missing or older than the source .md."""
    if not target_pdf.exists():
        return True
    return os.path.getmtime(source_md) > os.path.getmtime(target_pdf)


def render_one(source_md, target_pdf):
    """Compile a single .md to .pdf via motion_to_pdf.py."""
    target_pdf.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(MOTION_TO_PDF),
        str(source_md),
        str(target_pdf),
        STYLESHEET_FLAG,
        MARGIN,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0, proc.stderr


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    if not SOURCE_ROOT.is_dir():
        print(f"ERROR: source root not found: {SOURCE_ROOT}")
        sys.exit(1)

    targets = discover_targets()
    if not targets:
        print("No target .md files found.")
        sys.exit(0)

    print(f"Source:  {SOURCE_ROOT}")
    print(f"Target:  {TARGET_ROOT}")
    print(f"Found {len(targets)} target Markdown files.\n")
    print(f"{'SOURCE .MD':<58} {'STATUS'}")
    print("-" * 70)

    if dry_run:
        for src, dst in targets:
            state = "would render" if needs_render(src, dst) else "up to date"
            print(f"{str(src):<58} {state}")
        print("\nDry run — no PDFs generated.")
        return

    failures = []
    rendered = 0
    skipped = 0

    for src, dst in targets:
        rel = src.relative_to(SOURCE_ROOT)
        src_str = str(rel)
        if not force and not needs_render(src, dst):
            print(f"{src_str:<58} SKIPPED (up to date)")
            skipped += 1
            continue

        ok, err = render_one(src, dst)
        if ok and dst.exists() and dst.stat().st_size > 0:
            print(f"{src_str:<58} SUCCESS -> {dst}")
            rendered += 1
        else:
            print(f"{src_str:<58} FAILED")
            if err:
                print(f"    stderr: {err.strip()[-500:]}")
            failures.append(str(rel))

    print("\n" + "=" * 70)
    print(f"SUMMARY: {rendered} rendered, {skipped} skipped, {len(failures)} failed")
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"Output directory: {TARGET_ROOT}")


if __name__ == "__main__":
    main()