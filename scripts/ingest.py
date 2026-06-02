#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Ingest PDFs into 25FA152 with auto-classification.

Drop PDFs into 25FA152/INGEST/, then:

  # Full mechanical pipeline: convert, classify, route, RAG sync, FILEMAP
    uv run dc13_hive/scripts/ingest.py --auto --rag --filemap

  # Dry-run: preview classification and routing
    uv run dc13_hive/scripts/ingest.py --auto --dry-run

  # Sanitize filenames using content-extracted titles (overrides random names)
    uv run dc13_hive/scripts/ingest.py --auto --sanitize --rag --filemap

  # Route everything to a specific directory (bypass auto-classify)
    uv run dc13_hive/scripts/ingest.py --target 04_DONATELLO_FILINGS --rag

  # Direct path (overrides INGEST/ scan)
    uv run dc13_hive/scripts/ingest.py --file /path/to/document.pdf --rag

PDF->MD conversion is delegated to sync_legal_docs.py (single source of truth).
No duplicate conversion logic lives here.

Auto-classification reads extracted text and checks:
  Signature blocks (most reliable for party attribution)
  "Petitioner" / "Respondent" header fields
  Filename cues

KNOWN LIMITATIONS:
  Party attribution (David vs Pauletta) is imperfect — both parties use the
  same ATJ form templates. Always review auto-classified results before
  relying on them for legal strategy. The --sanitize flag generates names
  from form content but human verification is strongly recommended.

For each PDF, delegates .md twin creation to sync_legal_docs.py, then copies
both to the target folder. Cleans INGEST/ on success.

Use --rag to also copy into 25FA152_rag/ (flat path-encoded).
Use --filemap (-f) to regenerate FILEMAP.md after processing.
Use --sanitize (-s) to generate content-based names for all files.
"""

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CASE_DIR = Path("/Users/macuser/LAW_LAB/25FA152")
LEGAL_DIR = CASE_DIR / "LEGAL_FILE"
INGEST_DIR = CASE_DIR / "INGEST"
RAG_DIR = Path("/Users/macuser/LAW_LAB/25FA152_rag")

TARGETS = {
    "01_DRAFTS": LEGAL_DIR / "01_DRAFTS",
    "02_ACTIVE_ORDERS": LEGAL_DIR / "02_ACTIVE_ORDERS",
    "03_BYERS_FILINGS": LEGAL_DIR / "03_BYERS_FILINGS",
    "04_DONATELLO_FILINGS": LEGAL_DIR / "04_DONATELLO_FILINGS",
    "99_MISC": LEGAL_DIR / "99_MISC",
}

SKIP_CHARS = str.maketrans({" ": "_", "\t": "_", "(": "", ")": "", ",": "", "'": ""})

SYNC_SCRIPT = Path(__file__).resolve().parent / "sync_legal_docs.py"

# ── Auto-rename: replace random filenames (PDF7247, etc.) with content-based names ──

RANDOM_NAME_RE = re.compile(r"^PDF\d+$", re.IGNORECASE)


def build_descriptive_name(text: str, filename: str) -> str | None:
    """Build a descriptive filename stem from document content.
    Returns None if insufficient content to build a meaningful name."""
    case_num = _extract_case_number(text)
    date_str = _extract_filing_date(text)
    doc_type = _extract_doc_type(text)
    party = _extract_party(text)

    parts = []
    if date_str:
        parts.append(date_str)
    else:
        # Use modification date as fallback?
        pass

    if doc_type:
        # Truncate long doc types
        dt = doc_type[:80]
        parts.append(dt)

    if case_num:
        parts.append(case_num)

    if party:
        parts.append(party)

    if not parts:
        return None

    name = "_".join(parts).translate(SKIP_CHARS)
    # Remove trailing punctuation/underscores
    name = name.strip("_")
    return name if len(name) > 10 else None


def auto_rename(text: str, filename: str) -> str | None:
    """Generate a descriptive filename stem from document content.
    Only renames filenames that look random (PDF7247, etc.).
    Returns None if the original name is meaningful (not random)."""
    stem, _ = os.path.splitext(filename)
    if RANDOM_NAME_RE.match(stem):
        return build_descriptive_name(text, filename)
    return None


def sanitize_name(text: str, filename: str) -> str | None:
    """Generate a proper name for any file, regardless of original name.
    Only returns a new name if it differs significantly from the original."""
    new = build_descriptive_name(text, filename)
    if not new:
        return None
    old_stem, _ = os.path.splitext(filename)
    # Sanitize old stem
    old_clean = re.sub(r"[^A-Za-z0-9_]", "", old_stem.replace(" ", "_")).upper()[:30]
    new_clean = re.sub(r"[^A-Za-z0-9_]", "", new).upper()[:30]
    if old_clean == new_clean or new_clean in old_clean or old_clean in new_clean:
        return None  # Name already captures the same info
    return new


def _extract_case_number(text: str) -> str | None:
    # Fix OCR zero-instead-of-O before matching
    clean = re.sub(r"(\d{2,})0P(\d)", r"\1OP\2", text)
    clean = re.sub(r"(\d{2,})0FA(\d)", r"\1FA\2", clean)
    m = re.search(
        r"(\d{4,}(?:OP|FA|CF|CM|MR|CH|DT|DV|JA|LM|MC|P2|SC)\d{3,})",
        clean,
    )
    if m:
        raw = m.group(1)
        # Strip leading zeros in suffix: "2024OP000613" → "2024OP613"
        raw = re.sub(r"(OP|FA|CF|CM|MR|CH|DT|DV|JA|LM|MC|P2|SC)\d{2}0+(\d+)",
                     lambda m: m.group(1) + m.group(2), raw)
        # Normalize to 2‑digit year: "2024OP613" → "24OP613"
        raw = re.sub(r"^20(\d{2}(?:OP|FA|CF|CM|MR|CH|DT|DV|JA|LM|MC|P2|SC))",
                     r"\1", raw)
        return raw
    return None


def _extract_filing_date(text: str) -> str | None:
    m = re.search(r"FILED\s+(\w{3,9}\s+\d{1,2}\s+\d{4})", text)
    if m:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                dt = datetime.datetime.strptime(m.group(1), fmt)
                return dt.strftime("%Y_%m_%d")
            except ValueError:
                pass
    m = re.search(r"Date:\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        parts = m.group(1).split("/")
        return f"{parts[2]}_{parts[0]}_{parts[1]}"
    return None


def _extract_doc_type(text: str) -> str | None:
    head = text[:2000].upper()

    # Priority: ATJ form "Motion to:" title line (section 1 of ATJ 801.7)
    m = re.search(
        r"Motion to:\s*_*([A-Za-z0-9\s,;'/-]+?)_*\s*$",
        head,
        re.MULTILINE,
    )
    if m:
        title = m.group(1).strip().rstrip("_").strip()
        # Normalize: collapse whitespace, uppercase
        title = re.sub(r"[_]+", " ", title)
        title = re.sub(r"\s+", "_", title.strip())[:60]
        return f"MOTION_{title}"

    # ATJ form "APPEARANCE"
    if "APPEARANCE (CIVIL)" in head or head.strip().startswith("APPEARANCE"):
        return "APPEARANCE"

    # ATJ form "AFFIRMATIVE DEFENSES"
    if "AFFIRMATIVE DEFENSES" in head:
        return "AFFIRMATIVE_DEFENSES"

    # ATJ form "ANSWER OR RESPONSE"
    if "ANSWER OR RESPONSE" in head:
        return "ANSWER"

    # ATJ form "NOTICE OF COURT DATE FOR MOTION"
    if "NOTICE OF COURT DATE" in head:
        m = re.search(r"Motion to:\s*_*([A-Za-z0-9\s,;'/-]+?)_*\s*$", head, re.MULTILINE)
        if m:
            title = re.sub(r"[_]+", " ", m.group(1).strip())
            title = re.sub(r"\s+", "_", title.strip())[:50]
            return f"NOTICE_{title}" if title else "NOTICE"
        return "NOTICE"

    # Multi-line patterns: "PETITION FOR\nORDER OF PROTECTION"
    m = re.search(
        r"PETITION\s+FOR\s*\n\s*((?:ORDER\s+OF\s+PROTECTION"
        r"|PROTECTIVE\s+ORDER|DISSOLUTION|CUSTODY|GUARDIANSHIP"
        r"|ADOPTION|NAME\s+CHANGE|EXPUNGEMENT|RELIEF"
        r"|TEMPORARY\s+RESTRAINING\s+ORDER|MODIFICATION"
        r"|RELOCATION|CONTEMPT|ENFORCEMENT|DISCOVERY"
        r"|SANCTIONS|ATTORNEY\s+FEES|ATTORNEYS\s+FEES"
        r"|APPOINTMENT|DISMISSAL|SUMMARY\s+JUDGMENT"
        r"|EMERGENCY|SUPPORT))",
        head,
    )
    if m:
        return f"PETITION_FOR_{m.group(1).strip().replace(' ', '_')}"

    # Single-line patterns
    lines = head.split("\n")
    for raw in lines:
        line = raw.strip()
        if len(line) < 5 or line.startswith("INSTRUCTION") or line.startswith("PAGE"):
            continue
        m = re.match(r"PETITION\s+FOR\s+(.+)", line)
        if m:
            label = re.sub(r"[^A-Z0-9_]", "", m.group(1).strip().replace(" ", "_"))[:40]
            return f"PETITION_FOR_{label}" if label else "PETITION"
        if line in (
            "ORDER",
            "JUDGMENT",
            "ORDER OF PROTECTION",
            "EMERGENCY ORDER OF PROTECTION",
            "PLENARY ORDER OF PROTECTION",
        ):
            return line.replace(" ", "_")
        if "MOTION" in line and len(line) < 80:
            label = re.sub(r"MOTION\s+", "", line).strip()[:40]
            label = re.sub(r"[^A-Z0-9_]", "", label.replace(" ", "_"))
            return f"MOTION_{label}" if label else "MOTION"
        if line.startswith("ANSWER"):
            return "ANSWER"
        if line.startswith("RESPONSE"):
            return "RESPONSE"
    return None


def _extract_party(text: str) -> str | None:
    """Identify filer from signature block (most reliable), then header, then body text."""
    # Priority 1: Signature block — "Print Name: Pauletta Donatello" near signature
    sig = re.search(
        r"Signature\s*/s[^]*?Print\s*Name\s*_*([A-Za-z\s]+?)_*",
        text[:2000],
    )
    if sig:
        name = sig.group(1).strip().upper()
        if "PAULETTA" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Priority 2: "I am filing the Motion. I am the: [x] Defendant/Respondent"
    filer_checkbox = re.search(
        r"I am filing the Motion\.\s*I am the:\s*\n\s*[^]*?(?:Plaintiff|Defendant)",
        text[:1500],
    )
    if filer_checkbox:
        block = filer_checkbox.group(0)
        if "Defendant" in block or "Respondent" in block:
            # Respondent is Pauletta in 25FA152, but could be David in OP cases
            # Check case number to determine
            case = _extract_case_number(text)
            if case and "OP" in (case or ""):
                return "by_Pauletta"  # Pauletta is typically Petitioner in OPs
            return "by_Pauletta"  # Default: Respondent = Pauletta in 25FA152
        if "Plaintiff" in block or "Petitioner" in block:
            case = _extract_case_number(text)
            if case and "OP" in (case or ""):
                return "by_David"  # David is typically Respondent in OPs
            return "by_David"  # Default: Petitioner = David in 25FA152

    # Priority 3: Header fields
    m = re.search(r"Petitioner:\s*([A-Za-z\s]+?)(?:\n|\(|\d)", text)
    if m:
        name = m.group(1).strip().upper()
        if "PAULETTA" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Priority 4: "I am completing this form for myself" near signature name
    sig_self = re.search(
        r"I am completing this form for myself[^]*?Print Name\s*_*([A-Za-z\s]+?)_*",
        text[:2500],
    )
    if sig_self:
        name = sig_self.group(1).strip().upper()
        if "PAULETTA" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Body-text fallback
    upper = text[:1000].upper()
    if "PAULETTA DONATELLO" in upper:
        return "by_Pauletta"
    if "DAVID BYERS" in upper:
        return "by_David"
    return None


# ── PDF -> MD via sync_legal_docs.py (single source of truth) ──


def convert_via_sync_legal(pdf_path: Path) -> tuple[Path | None, str]:
    """Delegate PDF->MD to sync_legal_docs.py. Returns (md_path | None, raw_text)."""
    md_path = pdf_path.with_suffix(".md")
    try:
        subprocess.run(
            ["uv", "run", str(SYNC_SCRIPT), str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
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
    parts = re.split(r"^---\s*$", content, flags=re.MULTILINE, maxsplit=2)
    if len(parts) >= 3:
        body = parts[2].strip()
    else:
        body = content.strip()
    # Strip structural path context header if present
    body = re.sub(
        r"^# Structural Path Context\n.*?\n---\n\n", "", body, flags=re.DOTALL
    )
    return body.strip()


# ── Auto-classification ──


def auto_classify(text: str, filename: str) -> str:
    """Return target folder name based on text analysis.

    Note: Party attribution (David vs Pauletta) is unreliable from text alone
    because both parties use the same ATJ forms. The signature block is the
    most reliable signal. When in doubt, routes to 03_BYERS_FILINGS (default
    Petitioner) and flags for human review.
    """
    head = text[:1000].lower()
    fname = filename.lower()

    # OP / order of protection → related cases
    if "order of protection" in head or re.search(r"\bop\b", head):
        clean = re.sub(r"(\d{2,})0P(\d)", r"\1OP\2", text)
        m = re.search(r"(\d{4,}OP\d{3,})", clean)
        if m:
            case = m.group(1)
            case = re.sub(r"OP\d{2}0+(\d+)", r"OP\1", case)
            case = re.sub(r"^20(\d{2}OP)", r"\1", case)
            return f"05_RELATED_CASES/{case}"
        return "05_RELATED_CASES"

    # Court order / judgment
    if (
        head.startswith("order")
        or "judgment" in head
        or ("entered" in head and "order" in head)
    ):
        return "02_ACTIVE_ORDERS"

    # Signature-based party detection (most reliable)
    party = _extract_party(text)

    # Respondent filings (signature or explicit header match)
    if party == "by_Pauletta":
        return "04_DONATELLO_FILINGS"
    if party == "by_David":
        return "03_BYERS_FILINGS"

    # Fallback: header-based detection
    if "respondent" in head and ("answer" in head or "response" in head):
        return "04_DONATELLO_FILINGS"
    if "answer to" in head or "response to" in head:
        return "04_DONATELLO_FILINGS"

    # Petitioner filings header
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


def sync_to_rag(
    pdf_path: Path,
    md_path: Path | None,
    target_rel: str,
    dry_run: bool,
    custom_name: str | None = None,
):
    """Copy files to 25FA152_rag/ with path-encoded flat names."""
    flat_base = custom_name or pdf_path.name
    parts = ["LEGAL_FILE"] + target_rel.split("/") + [flat_base]
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


def process_file(
    pdf_path: Path,
    target: str | None,
    auto: bool,
    do_rag: bool,
    dry_run: bool,
    sanitize: bool = False,
):
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

    # Rename: try auto-rename for random names, or sanitize for all
    if sanitize and raw_text:
        new_stem = sanitize_name(raw_text, pdf_path.name)
        if new_stem:
            pdf_name = new_stem + ".pdf"
            md_name = (new_stem + ".md") if md_path else None
            print(f"    sanitized: {pdf_path.name} -> {pdf_name}")
        else:
            pdf_name = pdf_path.name
            md_name = md_path.name if md_path else None
            print(f"    name kept: {pdf_name}")
    elif auto:
        new_stem = auto_rename(raw_text, pdf_path.name)
        if new_stem:
            pdf_name = new_stem + ".pdf"
            md_name = None if not md_path else (new_stem + ".md")
            print(f"    renamed: {pdf_path.name} -> {pdf_name}")
        else:
            pdf_name = pdf_path.name
            md_name = md_path.name if md_path else None
    else:
        pdf_name = pdf_path.name
        md_name = md_path.name if md_path else None

    # Resolve target dir
    if target_rel.startswith("05_RELATED_CASES/"):
        target_dir = LEGAL_DIR / target_rel
    elif target_rel in TARGETS:
        target_dir = TARGETS[target_rel]
    else:
        target_dir = LEGAL_DIR / target_rel

    if dry_run:
        print(f"    would copy: {target_dir.name}/{pdf_name}")
        if md_path and md_name:
            print(f"    would copy: {target_dir.name}/{md_name}")
        if do_rag:
            sync_to_rag(pdf_path, md_path, target_rel, dry_run=True, custom_name=pdf_name)
        return True

    # Copy files
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, target_dir / pdf_name)
    print(f"    copied: {target_dir.name}/{pdf_name}")

    if md_path and md_name:
        shutil.copy2(md_path, target_dir / md_name)
        print(f"    copied: {target_dir.name}/{md_name}")

    # RAG sync (before INGEST cleanup while files still exist)
    if do_rag:
        sync_to_rag(pdf_path, md_path, target_rel, dry_run=False, custom_name=pdf_name)

    # Remove from INGEST/
    if str(pdf_path.parent).startswith(str(INGEST_DIR)):
        pdf_path.unlink()
        if md_path:
            md_path.unlink()
        print(f"    removed from INGEST/")

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    do_rag = "--rag" in sys.argv or "-r" in sys.argv
    do_filemap = "--filemap" in sys.argv or "-f" in sys.argv
    do_sanitize = "--sanitize" in sys.argv or "-s" in sys.argv
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
                print(
                    f"Error: file not found or not PDF: {single_file}", file=sys.stderr
                )
                sys.exit(1)

    print(f"Ingest: 25FA152/INGEST/ -> LEGAL_FILE/")
    print(f"Auto:    {auto}")
    print(f"Target:  {target or '(auto/detect)'}")
    print(f"RAG:     {do_rag}")
    print(f"Filemap: {do_filemap}")
    print(f"Sanitize:{do_sanitize}")
    print(f"Dry run: {dry_run}")
    print()

    if single_file:
        process_file(single_file, target, auto, do_rag, dry_run, do_sanitize)
    else:
        if not INGEST_DIR.exists():
            print(f"No INGEST/ directory found at {INGEST_DIR}")
            print("Create it: mkdir -p 25FA152/INGEST")
            sys.exit(1)

        pdfs = sorted(INGEST_DIR.glob("*.pdf"))
        if not pdfs:
            print("No PDFs found in INGEST/")
            return

        count = 0
        for pdf in pdfs:
            ok = process_file(pdf, target, auto, do_rag, dry_run, do_sanitize)
            if ok:
                count += 1

        print(f"\n{'─' * 50}")
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
