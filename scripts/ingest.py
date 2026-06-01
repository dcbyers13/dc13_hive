#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Ingest PDFs into 25fa152 with auto-classification.

Drop a PDF into 25fa152/INGEST/, then:

  # Dry-run: show what would happen
  uv run dc13_hive/scripts/ingest.py [--dry-run]

  # Auto-classify and route (with RAG sync + FILEMAP regeneration)
    uv run dc13_hive/scripts/ingest.py --auto --rag --filemap

    # Route to a specific directory
    uv run dc13_hive/scripts/ingest.py --target 03_BYERS_FILINGS [--rag] [--filemap]

    # Direct path (overrides INGEST/ scan)
    uv run dc13_hive/scripts/ingest.py --file /path/to/document.pdf

PDF->MD conversion is delegated to sync_legal_docs.py (single source of truth).
No duplicate conversion logic lives here.

Auto-classification reads first 500 chars of extracted text:
  "Petitioner" + "Motion" / "Petition"  → 03_BYERS_FILINGS
  "Respondent" / "Answer" / "Response"  → 04_DONATELLO_FILINGS
  "Order" / "Judgment"                  → 02_ACTIVE_ORDERS
  "OP" / "Order of Protection"          → 05_RELATED_CASES/<case_num>
  (fallback: 99_MISC)

For each PDF, delegates .md twin creation to sync_legal_docs.py, then copies both
to the target folder. Cleans INGEST/ on success.

Use --rag to also copy into 25fa152_rag/ (flat path-encoded).
"""

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

CASE_DIR = Path("/Users/macuser/LAW_LAB/25fa152")
LEGAL_DIR = CASE_DIR / "LEGAL_FILE"
INGEST_DIR = CASE_DIR / "INGEST"
RAG_DIR = Path("/Users/macuser/LAW_LAB/25fa152_rag")

TARGETS = {
    "01_DRAFTS": LEGAL_DIR / "01_DRAFTS",
    "02_ACTIVE_ORDERS": LEGAL_DIR / "02_ACTIVE_ORDERS",
    "03_BYERS_FILINGS": LEGAL_DIR / "03_BYERS_FILINGS",
    "04_DONATELLO_FILINGS": LEGAL_DIR / "04_DONATELLO_FILINGS",
    "99_MISC": LEGAL_DIR / "99_MISC",
}

SKIP_CHARS = str.maketrans({' ': '_', '\t': '_', '(': '', ')': '', ',': '', "'": ''})

SYNC_SCRIPT = Path(__file__).resolve().parent / "sync_legal_docs.py"


# ── PDF -> MD via sync_legal_docs.py (single source of truth) ──

def convert_via_sync_legal(pdf_path: Path) -> tuple[Path | None, str]:
    """Delegate PDF->MD to sync_legal_docs.py. Returns (md_path | None, raw_text)."""
    md_path = pdf_path.with_suffix(".md")
    try:
        subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), str(pdf_path)],
            capture_output=True, text=True, timeout=120, check=True,
        )
        if md_path.exists():
            raw = extract_raw_text(md_path)
            chars = len(raw.strip())
            print(f"    md twin created via sync_legal_docs.py ({chars} chars)")
            return md_path, raw
    except subprocess.CalledProcessError as e:
        print(f"    sync_legal_docs.py failed: {e.stderr.strip()}", file=sys.stderr)
    except Exception as e:
        print(f"    sync_legal_docs.py error: {e}", file=sys.stderr)
    return None, ""


def extract_raw_text(md_path: Path) -> str:
    """Strip sync_legal_docs frontmatter; return raw body text."""
    content = md_path.read_text(encoding="utf-8")
    # Strip yaml frontmatter between --- markers
    parts = re.split(r'^---\s*$', content, flags=re.MULTILINE, maxsplit=2)
    if len(parts) >= 3:
        body = parts[2].strip()
    else:
        body = content.strip()
    # Strip structural path context header if present
    body = re.sub(r'^# Structural Path Context\n.*?\n---\n\n', '', body, flags=re.DOTALL)
    return body.strip()


# ── Auto-classification ──

def auto_classify(text: str, filename: str) -> str:
    """Return target folder name based on text analysis."""
    head = text[:500].lower()
    fname = filename.lower()

    # OP / order of protection → related cases
    if "order of protection" in head or re.search(r'\bop\b', head):
        m = re.search(r'(\d{2,}OP\d+)', text)
        if m:
            case = m.group(1)
            return f"05_RELATED_CASES/{case}"
        return "05_RELATED_CASES"

    # Court order / judgment
    if head.startswith("order") or "judgment" in head or ("entered" in head and "order" in head):
        return "02_ACTIVE_ORDERS"

    # Respondent filings
    if "respondent" in head and ("answer" in head or "response" in head):
        return "04_DONATELLO_FILINGS"
    if "answer to" in head or "response to" in head:
        return "04_DONATELLO_FILINGS"

    # Petitioner filings
    if "petitioner" in head:
        if "motion" in head or "petition" in head or "exhibit" in head:
            return "03_BYERS_FILINGS"
        return "03_BYERS_FILINGS"

    # Filename cues
    if "motion" in fname or "petition" in fname or "exhibit" in fname:
        return "03_BYERS_FILINGS"
    if "answer" in fname or "response" in fname:
        return "04_DONATELLO_FILINGS"
    if "order" in fname or "judgment" in fname:
        return "02_ACTIVE_ORDERS"
    if "draft" in fname:
        return "01_DRAFTS"

    return "99_MISC"


# ── RAG sync ──

def sync_to_rag(pdf_path: Path, md_path: Path | None, target_rel: str, dry_run: bool):
    """Copy files to 25fa152_rag/ with path-encoded flat names."""
    parts = ["LEGAL_FILE"] + target_rel.split("/") + [pdf_path.name]
    flat_name = "__".join(parts).translate(SKIP_CHARS)
    flat_md_name = flat_name.rsplit(".", 1)[0] + ".md"

    rag_pdf = RAG_DIR / flat_name
    rag_md = RAG_DIR / flat_md_name

    if dry_run:
        print(f"    rag pdf -> {rag_pdf.name}")
        if md_path:
            print(f"    rag md  -> {rag_md.name}")
        return

    rag_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, rag_pdf)
    if md_path and md_path.exists():
        shutil.copy2(md_path, rag_md)
    print(f"    rag synced: {flat_name}")


# ── Main ──

def process_file(pdf_path: Path, target: str | None, auto: bool, do_rag: bool, dry_run: bool):
    """Process a single PDF: convert, route, optionally sync RAG."""
    print(f"\n  File: {pdf_path.name}")

    if not pdf_path.exists():
        print(f"    SKIP: not found")
        return False

    # Convert to md via sync_legal_docs.py; use raw text for classification
    md_path, raw_text = convert_via_sync_legal(pdf_path)

    # Determine target
    if target:
        target_rel = target
    elif auto:
        target_rel = auto_classify(raw_text, pdf_path.name)
        print(f"    classified -> {target_rel}")
    else:
        target_rel = "99_MISC"
        print(f"    default -> {target_rel}")

    # Resolve target dir
    if target_rel.startswith("05_RELATED_CASES/"):
        target_dir = LEGAL_DIR / target_rel
    elif target_rel in TARGETS:
        target_dir = TARGETS[target_rel]
    else:
        target_dir = LEGAL_DIR / target_rel

    if dry_run:
        print(f"    would copy to: {target_dir / pdf_path.name}")
        if md_path:
            print(f"    would copy md: {target_dir / md_path.name}")
        if do_rag:
            sync_to_rag(pdf_path, md_path, target_rel, dry_run=True)
        return True

    # Copy files
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, target_dir / pdf_path.name)
    print(f"    copied: {target_dir.name}/{pdf_path.name}")

    if md_path:
        shutil.copy2(md_path, target_dir / md_path.name)
        print(f"    copied: {target_dir.name}/{md_path.name}")

    # Remove from INGEST/
    if str(pdf_path.parent).startswith(str(INGEST_DIR)):
        pdf_path.unlink()
        if md_path:
            md_path.unlink()
        print(f"    removed from INGEST/")

    # RAG sync
    if do_rag:
        sync_to_rag(pdf_path, md_path, target_rel, dry_run=False)

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    do_rag = "--rag" in sys.argv or "-r" in sys.argv
    do_filemap = "--filemap" in sys.argv or "-f" in sys.argv
    auto = "--auto" in sys.argv or "-a" in sys.argv
    target = None

    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            target = sys.argv[idx + 1]

    single_file = None
    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 < len(sys.argv):
            single_file = Path(sys.argv[idx + 1]).resolve()
            if not single_file.exists() or single_file.suffix.lower() != ".pdf":
                print(f"Error: file not found or not PDF: {single_file}", file=sys.stderr)
                sys.exit(1)

    print(f"Ingest: 25fa152/INGEST/ -> LEGAL_FILE/")
    print(f"Auto:    {auto}")
    print(f"Target:  {target or '(auto/detect)'}")
    print(f"RAG:     {do_rag}")
    print(f"Filemap: {do_filemap}")
    print(f"Dry run: {dry_run}")
    print()

    if single_file:
        process_file(single_file, target, auto, do_rag, dry_run)
    else:
        if not INGEST_DIR.exists():
            print(f"No INGEST/ directory found at {INGEST_DIR}")
            print("Create it: mkdir -p 25fa152/INGEST")
            sys.exit(1)

        pdfs = sorted(INGEST_DIR.glob("*.pdf"))
        if not pdfs:
            print("No PDFs found in INGEST/")
            return

        count = 0
        for pdf in pdfs:
            ok = process_file(pdf, target, auto, do_rag, dry_run)
            if ok:
                count += 1

        print(f"\n{'─'*50}")
        if dry_run:
            print(f"Would process {count} files from INGEST/")
        else:
            print(f"Processed {count} files from INGEST/")

    if not dry_run and do_filemap:
        script = Path(__file__).resolve().parent / "filemap.sh"
        law_lab = Path(__file__).resolve().parents[2]
        print("\nRegenerating FILEMAP.md ...")
        subprocess.run(["bash", str(script)], cwd=str(law_lab), check=True)
        print("  done")

    if not dry_run and do_rag:
        print("\nTip: Run flatten_for_rag.py after batch ingests to sync RAG dir.")


if __name__ == "__main__":
    main()
