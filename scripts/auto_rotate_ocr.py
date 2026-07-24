#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

# /// script
# requires-python = ">=3.10"
# dependencies = ["PyMuPDF"]
# ///

"""
Auto-rotate and OCR scanned PDFs with mixed page orientations.

Detects rotated pages using Tesseract OSD (Orientation and Script Detection),
corrects orientation via PDF metadata, then runs OCR to produce clean Markdown.

Usage:
    # Fix rotation + OCR a single file
    uv run dc13_hive/scripts/auto_rotate_ocr.py input.pdf

    # Fix rotation only (no OCR), output to specified path
    uv run dc13_hive/scripts/auto_rotate_ocr.py input.pdf --output corrected.pdf

    # Batch process all PDFs in a directory
    uv run dc13_hive/scripts/auto_rotate_ocr.py --dir /path/to/pdfs/

    # Dry run — show which pages are rotated without fixing
    uv run dc13_hive/scripts/auto_rotate_ocr.py input.pdf --dry-run

Requires: tesseract with osd language pack (brew install tesseract)
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import fitz
except ImportError:
    print("Error: PyMuPDF not installed. Run: uv pip install PyMuPDF")
    sys.exit(1)


def detect_orientation(page, matrix=None):
    """Use Tesseract OSD to detect page orientation in degrees.

    Returns 0, 90, 180, or 270.
    """
    if matrix is None:
        matrix = fitz.Matrix(2, 2)

    pix = page.get_pixmap(matrix=matrix)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        pix.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["tesseract", tmp_path, "-", "--psm", "0"],
            capture_output=True, timeout=15,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        for line in stdout.split("\n"):
            if "Orientation in degrees" in line:
                return int(line.split(":")[1].strip())
    except Exception as e:
        print(f"  Warning: OSD failed for page: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return 0


def scan_rotations(doc, sample_interval=5):
    """Scan PDF for rotated pages. Returns dict {page_index: orientation}.

    Uses sampling for speed — only does full scan if rotation is detected.
    """
    total = doc.page_count
    matrix = fitz.Matrix(2, 2)

    # Phase 1: Quick sample
    sample_indices = list(range(0, total, sample_interval))
    needs_full_scan = False
    for idx in sample_indices:
        orient = detect_orientation(doc[idx], matrix)
        if orient != 0:
            needs_full_scan = True
            break

    if not needs_full_scan:
        return {}

    # Phase 2: Full scan
    print(f"  Rotation detected; scanning all {total} pages...")
    rotations = {}
    for idx in range(total):
        rotations[idx] = detect_orientation(doc[idx], matrix)
        if idx % 30 == 0 and idx > 0:
            print(f"    Scanned {idx+1}/{total}...")

    return rotations


def fix_rotation(pdf_path, output_path=None, dry_run=False):
    """Detect and fix rotated pages in a PDF.

    Args:
        pdf_path: Path to input PDF
        output_path: Path for corrected PDF (default: <name>_corrected.pdf)
        dry_run: If True, only report rotations without fixing

    Returns:
        Path to corrected PDF, or original path if no rotation found.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    print(f"Processing: {pdf_path.name} ({total} pages)")

    rotations = scan_rotations(doc)
    rotated_count = len(rotations)

    if rotated_count == 0:
        print("  No rotated pages detected.")
        doc.close()
        return str(pdf_path)

    # Report
    orient_counts = {}
    for orient in rotations.values():
        orient_counts[orient] = orient_counts.get(orient, 0) + 1
    print(f"  Found {rotated_count}/{total} rotated pages:")
    for orient, count in sorted(orient_counts.items()):
        print(f"    {orient}°: {count} pages")

    if dry_run:
        print("\n  Dry run — no changes made.")
        doc.close()
        return str(pdf_path)

    # Fix: set rotation metadata on each rotated page
    for idx, orient in rotations.items():
        doc[idx].set_rotation(orient)

    # Save
    if output_path:
        out = Path(output_path)
    else:
        out = pdf_path.parent / f"{pdf_path.stem}_corrected{pdf_path.suffix}"

    doc.save(str(out))
    doc.close()
    print(f"  Saved: {out.name} ({os.path.getsize(out) // 1024}KB)")
    return str(out)


def batch_process(directory, dry_run=False):
    """Process all PDFs in a directory."""
    directory = Path(directory)
    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {directory}")
        return

    print(f"Found {len(pdfs)} PDFs in {directory}")
    for pdf in pdfs:
        print(f"\n{'─' * 50}")
        fix_rotation(pdf, dry_run=dry_run)


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    output = None
    directory = None

    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 < len(args):
            output = args[idx + 1]

    if "--dir" in args:
        idx = args.index("--dir")
        if idx + 1 < len(args):
            directory = args[idx + 1]

    if directory:
        batch_process(directory, dry_run=dry_run)
    elif args and not args[0].startswith("--"):
        fix_rotation(args[0], output_path=output, dry_run=dry_run)
    else:
        print("Usage: auto_rotate_ocr.py <input.pdf> [--output path] [--dry-run]")
        print("       auto_rotate_ocr.py --dir <directory> [--dry-run]")
        sys.exit(1)


if __name__ == "__main__":
    main()
