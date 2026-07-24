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
Use --report-unscanned (-u) to list all image-only/low-text files in LEGAL_FILE.
    (runs independently of ingestion, no PDFs needed)
Use --track (-t) after ingestion to:
    1. Re-run extract_all_dates.py -> DATE_INDEX.md
    2. Cross-reference LEGAL_FILE -> UNPROCESSED.md
    3. Show which files haven't been date-indexed yet
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
EXTRACT_DATES_SCRIPT = Path(__file__).resolve().parent / "extract_all_dates.py"

REPROCESS_DIRS = (
    "01_DRAFTS",
    "02_ACTIVE_ORDERS",
    "03_BYERS_FILINGS",
    "04_DONATELLO_FILINGS",
    "05_RELATED_CASES",
    "99_MISC",
)

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


def add_date_prefix(stem: str, text: str) -> str:
    """Prepend filing date (or today) to filename stem.
    Strips vestigial leading draft prefixes (e.g. 0_, 1_).
    Skips if stem already starts with a date like 2026_06_02_."""
    if re.match(r"^\d{4}_\d{2}_\d{2}[_-]", stem):
        return stem
    stem = re.sub(r"^\d+_", "", stem)  # strip 0_, 1_, etc.
    dt_str = _extract_filing_date(text) or datetime.datetime.now().strftime("%Y_%m_%d")
    return f"{dt_str}_{stem}" if not stem.startswith(dt_str) else stem


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


def _normalize_ocr_names(text: str) -> str:
    """Remove OCR underscore-spacing between letters for name matching.
    
    ATJ form text often produces _P_a_u_l_e_t_t_a_ instead of Pauletta.
    Also strips underscore runs used as handwritten fill blanks (e.g., ___).
    """
    # Pass 1: _P -> P, _a -> a (underscore before any letter)
    text = re.sub(r'_([A-Za-z])', r'\1', text)
    # Pass 2: a_ -> a (underscore after letter, before whitespace/end)
    text = re.sub(r'([A-Za-z])_(?=\s|,|\n|$)', r'\1', text)
    # Pass 3: remove underscore runs before whitespace (form fill lines)
    text = re.sub(r'_+(?=\s|\n|$)', '', text)
    return text


def _extract_party(text: str) -> str | None:
    """Identify filer from signature block (most reliable), then header, then body text."""
    # Normalize OCR underscore spacing for name matching throughout
    text = _normalize_ocr_names(text)

    # Priority 1: Signature block — "Print Name: Pauletta Donatello" near signature
    # Use greedy capture + boundary: name ends at space/comma/newline/end
    sig = re.search(
        r"Signature\s*/s[\s\S]*?Print\s*Name\s*([A-Za-z\s.]+?)(?:\s|,|\n|$)",
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
        r"I am filing the Motion\.\s*I am the:\s*\n\s*[\s\S]*?(?:Plaintiff|Defendant)",
        text[:1500],
    )
    if filer_checkbox:
        block = filer_checkbox.group(0)
        if "Defendant" in block or "Respondent" in block:
            # Respondent is David in OP cases, Pauletta in 25FA152
            case = _extract_case_number(text)
            if case and "OP" in (case or ""):
                return "by_David"  # In OPs, Respondent = David
            return "by_Pauletta"  # In 25FA152, Respondent = Pauletta
        if "Plaintiff" in block or "Petitioner" in block:
            # Petitioner is Pauletta in OP cases, David in 25FA152
            case = _extract_case_number(text)
            if case and "OP" in (case or ""):
                return "by_Pauletta"  # In OPs, Petitioner = Pauletta
            return "by_David"  # In 25FA152, Petitioner = David

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
        r"I am completing this form for myself[\s\S]*?Print Name\s*([A-Za-z\s.]+?)(?:\s|,|\n|$)",
        text[:2500],
    )
    if sig_self:
        name = sig_self.group(1).strip().upper()
        if "PAULETTA" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Priority 5: ATJ form "My name is: [Filer]" — direct self-identification.
    # Handles underscore-spaced OCR text via normalization above.
    m = re.search(
        r"my name is:\s*([a-z][a-z\s.]+?)(?:\n|$)",
        text[:2000], re.IGNORECASE
    )
    if m:
        name = m.group(1).strip().upper()
        if "PAULETTA" in name or "DONATELLO" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Priority 6: "NOW COMES the Petitioner/Respondent, [Name]"
    # Most reliable filer indicator for drafted (non-ATJ) documents.
    m = re.search(
        r"NOW COMES the (Petitioner|Respondent),\s*([A-Za-z\s.]+?)\s*,",
        text[:2000], re.IGNORECASE
    )
    if m:
        name = m.group(2).strip().upper()
        if "PAULETTA" in name or "DONATELLO" in name:
            return "by_Pauletta"
        if "DAVID" in name or "BYERS" in name:
            return "by_David"

    # Priority 6: Signature-area fallback (last 500 chars).
    # Avoids caption-area name collision (both parties listed in header).
    tail = text[-500:].upper()
    if "DAVID" in tail or "BYERS" in tail:
        return "by_David"
    if "PAULETTA" in tail or "DONATELLO" in tail:
        return "by_Pauletta"
    return None


# ── OCR text normalization & cleanup ──


def _fix_common_prose(text: str) -> str:
    """Cross-document prose and administrative typo corrections."""
    fixes = {
        r"\blvlr\.\b": "Mr.",
        r"\b2id\b": "2nd",
        r"\boublic\.access\b": "public.access",
        r"\bilaq\.qov\b": "ilag.gov",
        r"\bKa\s+neSheriff\.com\b": "KaneSheriff.com",
        r"\bSherifFs\b": "Sheriff's",
        r"\bBYE\s+RS\b": "BYERS",
    }
    for pattern, replacement in fixes.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _is_jail_record(text: str) -> bool:
    """Detect whether text is a jail/custody record."""
    head = text[:500].lower()
    return "inmate" in head or "jacket" in head


def _is_atj_court_form(text: str) -> bool:
    """Detect whether text is an Illinois ATJ standardized court form."""
    head = text[:500].lower()
    keywords = [
        "answer or response", "motion to:", "affirmative defenses",
        "735 ilcs", "atj 140", "atj 1403", "atj 1405",
        "plaintiff/petitioner or in re:", "defendants/respondents:",
    ]
    return any(kw in head for kw in keywords)


def _clean_jail_table_data(text: str) -> str:
    """Token reconstruction and pipe-table formatting for jail custody records."""
    char_map = {
        "L": "1", "l": "1", "t": "1", "T": "1", "r": "1",
        "o": "0", "O": "0",
        "s": "5", "S": "5",
        "z": "2", "Z": "2",
        "a": "4", "A": "4",
        "g": "9",
    }

    lines = text.split("\n")
    processed_lines = []
    in_table_block = False
    table_rows = []

    for line in lines:
        if "Inmate" in line or "Jacket" in line or "BYERS," in line:
            in_table_block = True

            line = re.sub(r"(\d),(\d{5})", r"\1\2", line)
            line = re.sub(r"(\b[0-9A-Za-z/]{6,10})(\d{2}:\d{2})\b", r"\1 \2", line)

            for m in re.finditer(r"\b([0-9A-Za-z]{1,2})/([0-9A-Za-z]{1,2})/([0-9A-Za-z]{2,4})\b", line):
                raw = m.group(0)
                fixed = "".join(char_map.get(c, c) for c in raw)
                fixed = fixed.replace("2078", "2018").replace("207a", "2014").replace("2074", "2014")
                line = line.replace(raw, fixed)

            for m in re.finditer(r"\b([0-9A-Za-z]{1,2})[:\.]([0-9A-Za-z]{2})\b", line):
                raw = m.group(0)
                fixed = "".join(char_map.get(c, c) for c in raw).replace(".", ":")
                line = line.replace(raw, fixed)

            line = re.sub(r"\s+", " ", line).strip()

            if "BYERS," in line:
                parts = line.split(" ")
                if len(parts) >= 7:
                    name = f"{parts[0]} {parts[1]} {parts[2]}"
                    jacket = parts[3]
                    booking = f"{parts[4]} {parts[5]}"
                    release = f"{parts[6]} {parts[7]}" if len(parts) >= 8 else ""
                    line = f"| {name} | {jacket} | {booking} | {release} |"
                table_rows.append(line)
                continue
            elif "Jacket" in line or "Booking" in line:
                processed_lines.append("\n| Inmate Name | Jacket Number | Booking Date/Time | Release Date/Time |")
                processed_lines.append("| :--- | :--- | :--- | :--- |")
                continue
        else:
            if in_table_block and table_rows:
                processed_lines.extend(table_rows)
                processed_lines.append("\n")
                table_rows = []
                in_table_block = False
            processed_lines.append(line)

    if table_rows:
        processed_lines.extend(table_rows)

    return "\n".join(processed_lines)


def _clean_atj_court_form_data(text: str) -> str:
    """Clean Illinois ATJ standardized court form OCR artifacts.

    Stages:
      1. Checkbox standardization (PUA hex + named glyphs → [x] / [ ])
      2. Markdown underscore protection (preserve _italic_ and __bold__)
      3. Fill-blank underscore stripping (form entry lines)
      4. Restore markdown
      5. Smashed word segmentation (narrow-form concatenations)
      6. Boilerplate & footer scrubbing (remove ATJ structural footers)
      7. Punctuation spacing heuristics (fix smashed legal numbering)
    """
    # ── STAGE 1: Checkbox Standardization ──
    # Match any PUA checkbox character (U+E000–U+F8FF), plus known glyphs
    # Checked: PUA char adjacent to l/4/x, or x before PUA char, or checkmark glyphs
    text = re.sub(r'[\uE000-\uF8FF][l4x]|x[\uE000-\uF8FF]', '[x]', text)
    text = re.sub(r'[\u2713\u2714\u2717\u2718]', '[x]', text)  # ✓ ✔ ✗ ✘
    text = re.sub(r'[\uE000-\uF8FF]', '[ ]', text)
    text = re.sub(r'[\u25CB\u25EF]', '[ ]', text)  # ○ ◯
    # Guard: fix malformed "[ ]]" artifacts from adjacent bracket characters
    text = re.sub(r'\[ \]\]', '[ ]', text)

    # ── STAGE 2: Protect Markdown Syntax ──
    md_tokens = {}

    def _save_md(m):
        t = f"\x00MD{len(md_tokens)}\x00"
        md_tokens[t] = m.group(0)
        return t

    text = re.sub(r'(?<!\w)_(\w[^_]*?)_(?!\w)', _save_md, text)
    text = re.sub(r'(?<!\w)__(\w[^_]*?)__(?!\w)', _save_md, text)

    # ── STAGE 3: Form Underscore Stripping ──
    text = re.sub(r'(\d)______+', r'\1. ', text)
    text = re.sub(r'_\s*_{2,}', ' ', text)
    text = re.sub(r'\._{2,}', '. ', text)
    text = re.sub(r'(?<=\w)_+(?=\s|$)', ' ', text)
    text = re.sub(r'^_{3,}\s*$', '', text, flags=re.MULTILINE)
    # Line-by-line space collapsing: skip pipe-containing lines to protect table layout
    spaced_lines = []
    for _line in text.split('\n'):
        if '|' in _line:
            spaced_lines.append(_line)
        else:
            spaced_lines.append(re.sub(r'  +', ' ', _line))
    text = '\n'.join(spaced_lines)

    # ── STAGE 4: Restore Markdown ──
    for token, original in md_tokens.items():
        text = text.replace(token, original)

    # ── STAGE 5: Smashed Word Segmentation ──
    smash_map = {
        r'AllocationJudgment': 'Allocation Judgment',
        r'decision-makingregarding': 'decision-making regarding',
        r'healthcareand': 'healthcare and',
        r'unresolveddisputes': 'unresolved disputes',
        r'Respondentdoesnotknow': 'Respondent does not know',
        r"Petitioner'sprecise": "Petitioner's precise",
        r'internalcriteria': 'internal criteria',
        r'forwhatheconsiders': 'for what he considers',
        r'self_-harm': 'self-harm',
    }
    for pattern, replacement in smash_map.items():
        text = re.sub(pattern, replacement, text)

    # ── STAGE 6: Boilerplate & Footer Scrubbing ──
    # Remove isolated ATJ form revision stamps on their own line
    text = re.sub(
        r'^ATJ \d+\.\d+ \s* Page \d+ of \d+ \s* \(\d{2}/\d{2}\) \s*$',
        '',
        text,
        flags=re.MULTILINE,
    )
    # Remove standalone revision year markers
    text = re.sub(r'^\(\d{2}/\d{2}\)\s*$', '', text, flags=re.MULTILINE)
    # Strip trailing whitespace from lines that are now empty after scrubbing
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    # Collapse runs of 3+ blank lines to at most 2
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    # ── STAGE 7: Punctuation Spacing Heuristics ──
    # Protect markdown link URLs from colon spacing
    link_tokens = {}

    def _save_link(m):
        t = f"\x00LN{len(link_tokens)}\x00"
        link_tokens[t] = m.group(0)
        return t

    text = re.sub(r'\]\([^)]+\)', _save_link, text)
    # Fix smashed form colons: "COUNTY:DeKalb" -> "COUNTY: DeKalb"
    # Only fire on alphabetic-left contexts to avoid splitting timestamps (6:14 PM)
    text = re.sub(r'([A-Za-z]):([A-Za-z0-9])', r'\1: \2', text)
    # Restore markdown link URLs
    for token, original in link_tokens.items():
        text = text.replace(token, original)
    # Fix smashed legal numbering: "1.NAME" -> "1. NAME"
    text = re.sub(r'(?<=\d\.)(?=[A-Z])', ' ', text)
    text = re.sub(r'(?<=\d\.)(?=[a-z])', ' ', text)
    # Fix smashed section letters: "A.NAME" -> "A. NAME"
    text = re.sub(r"(?<=[A-Z]\.)(?=[A-Z])", ' ', text)
    # Ensure space after section/subsection dividers in run-on text
    text = re.sub(r'(?<=[.\)])(?=[A-Z][a-z]{2,})', ' ', text)
    # Clean any double spaces created by heuristics
    text = re.sub(r'  +', ' ', text)

    return text


def normalize_extracted_text(text: str) -> str:
    """Route to document-type-specific cleaner based on content signals.

    Applies cross-document prose fixes universally, then dispatches to
    specialized cleaners for jail records and ATJ court forms.
    """
    # Stage 0: Universal prose fixes (applies to all document types)
    text = _fix_common_prose(text)

    # Route to specialized cleaner
    if _is_jail_record(text):
        text = _clean_jail_table_data(text)
    elif _is_atj_court_form(text):
        text = _clean_atj_court_form_data(text)

    return text


# ── OCR quality detection ──


def _detect_ocr_quality(text: str, current_status: str = "good") -> str:
    """Re-check OCR quality from extracted text content.
    Downgrades over-optimistic status if text is too sparse.
    Returns 'image_only', 'needs_review', or the current status."""
    if current_status == "image_only":
        return current_status
    clean = re.sub(r"--- Page Break ---", "", text)
    clean = re.sub(r"\s+", "", clean).strip()
    if len(clean) < 50:
        return "image_only"
    if len(clean) < 200:
        return "needs_review"
    return current_status


# ── PDF -> MD via sync_legal_docs.py (single source of truth) ──


def convert_via_sync_legal(pdf_path: Path) -> tuple[Path | None, str, str]:
    """Delegate PDF->MD to sync_legal_docs.py. Returns (md_path, raw_text, ocr_status)."""
    md_path = pdf_path.with_suffix(".md")
    try:
        subprocess.run(
            ["uv", "run", str(SYNC_SCRIPT), str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=1800,
            check=True,
        )
        if md_path.exists():
            raw, ocr_status = extract_raw_text(md_path)
            # Re-check OCR quality — sync_legal may have been optimistic
            ocr_status = _detect_ocr_quality(raw, ocr_status)
            chars = len(raw.strip())
            status_flag = f" [{ocr_status}]" if ocr_status != "good" else ""
            print(f"    md twin created via sync_legal_docs.py ({chars} chars{status_flag})")
            return md_path, raw, ocr_status
    except subprocess.CalledProcessError as e:
        print(f"    sync_legal_docs.py failed: {e.stderr.strip()}", file=sys.stderr)
    except Exception as e:
        print(f"    sync_legal_docs.py error: {e}", file=sys.stderr)
    return None, "", "good"


def extract_raw_text(md_path: Path) -> tuple[str, str]:
    """Strip sync_legal_docs frontmatter; return (body_text, ocr_status)."""
    content = md_path.read_text(encoding="utf-8")
    ocr_status = "good"
    # Parse yaml frontmatter between --- markers
    parts = re.split(r"^---\s*$", content, flags=re.MULTILINE, maxsplit=2)
    if len(parts) >= 3:
        frontmatter = parts[1]
        body = parts[2].strip()
        m = re.search(r"ocr_status:\s*(\S+)", frontmatter)
        if m:
            ocr_status = m.group(1)
    else:
        body = content.strip()
    # Strip structural path context header if present
    body = re.sub(
        r"^# Structural Path Context\n.*?\n---\n\n", "", body, flags=re.DOTALL
    )
    return body.strip(), ocr_status


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
    # Guard: "Petitioner's Response" should NOT route to Donatello
    if ("respondent" in head and ("answer" in head or "response" in head)
            and "petitioner" not in head):
        return "04_DONATELLO_FILINGS"
    if ("answer to" in head or "response to" in head) and "petitioner" not in head:
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
    ocr_status: str = "good",
    dry_run: bool = False,
    custom_name: str | None = None,
    raw_body: str | None = None,
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

    if md_path and md_path.exists():
        if raw_body is not None:
            # Write enriched frontmatter + body
            virtual = f"LEGAL_FILE/{target_rel}/{custom_name or pdf_path.name}"
            original = custom_name or pdf_path.name
            fm = (
                "---\n"
                f"original_name: {original}\n"
                f"virtual_path: {virtual}\n"
                f"ocr_status: {ocr_status}\n"
                "---\n\n"
            )
            rag_md.write_text(fm + raw_body + "\n", encoding="utf-8")
        else:
            rag_md.parent.mkdir(parents=True, exist_ok=True)
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
    md_path, raw_text, ocr_status = convert_via_sync_legal(pdf_path)

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

    # Prepend date to filename (from document text or today)
    if raw_text:
        old_pdf = pdf_name
        stem, ext = os.path.splitext(pdf_name)
        new_stem = add_date_prefix(stem, raw_text)
        pdf_name = new_stem + ext
        if md_name:
            md_stem, md_ext = os.path.splitext(md_name)
            md_name = add_date_prefix(md_stem, raw_text) + md_ext
        if pdf_name != old_pdf:
            print(f"    date-prefixed: {old_pdf} -> {pdf_name}")

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
            sync_to_rag(pdf_path, md_path, target_rel, dry_run=True, ocr_status=ocr_status, custom_name=pdf_name)
        return True

    # Extract raw body and get ocr_status
    raw_body = None
    if md_path and md_path.exists():
        raw_body, ocr_status = extract_raw_text(md_path)
        # Apply normalization shield to clean historical records
        raw_body = normalize_extracted_text(raw_body)
        ocr_status = _detect_ocr_quality(raw_body, ocr_status)

    # Copy files
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, target_dir / pdf_name)
    print(f"    copied: {target_dir.name}/{pdf_name}")

    if md_path and md_name and raw_body:
        target_md = target_dir / md_name
        virtual = f"LEGAL_FILE/{target_rel}/{md_name}"
        original = md_name
        filestamp_val = _compute_filestamp(target_rel)
        stamp_text = _detect_filestamp_text(raw_body)
        if not stamp_text:
            stamp_text = "waiting"
            # Warn: unstamped file going into a FILINGS directory
            if filestamp_val == "true":
                print(f"    ⚠️  WARNING: No filestamp detected — file routed to {target_rel} unstamped")
                print(f"             Replace with file-stamped version before court use")
        if any(c in stamp_text for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "\"")):
            safe_stamp = stamp_text.replace('"', "'")
            stamp_line = f'filestamp_text: "{safe_stamp}"\n'
        else:
            stamp_line = f"filestamp_text: {stamp_text}\n"
        fm = (
            "---\n"
            f"original_name: {original}\n"
            f"virtual_path: {virtual}\n"
            f"ocr_status: {ocr_status}\n"
            f"filestamp: {filestamp_val}\n"
            f"{stamp_line}"
            "---\n\n"
        )
        target_md.write_text(fm + raw_body + "\n", encoding="utf-8")
        print(f"    copied: {target_dir.name}/{md_name}")

    # RAG sync (before INGEST cleanup while files still exist)
    if do_rag:
        sync_to_rag(pdf_path, md_path if md_path and md_path.exists() else None, target_rel, ocr_status=ocr_status, dry_run=False, custom_name=pdf_name, raw_body=raw_body)

    # Remove from INGEST/
    if str(pdf_path.parent).startswith(str(INGEST_DIR)):
        pdf_path.unlink()
        if md_path:
            md_path.unlink()
        print(f"    removed from INGEST/")

    return True


# ── Library reprocessing engine ──


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body. Returns (frontmatter, body)."""
    stripped = content.lstrip("\n")
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            return parts[0] + "---" + parts[1] + "---", parts[2].lstrip("\n")
    return "", content


def _compute_filestamp(target_rel: str) -> str:
    """Return 'true' if target directory indicates a court-filed document, else 'false'.

    Documents in 01_DRAFTS/ are unfiled drafts; everything else has been
    file-stamped by the court clerk.
    """
    return "false" if target_rel.startswith("01_DRAFTS") else "true"


_FILESTAMP_PATTERNS: list[tuple[str, bool]] = [
    # e-filing acceptance stamp (most reliable)
    # Note: ATJ forms may add extra spaces like "4/21 /2026" — tolerate optional space
    (
        r"Accepted:\s*\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\s+\d{1,2}:\d{2}(?:\s*[AP]M)?"
        r"\s*(?:Reviewed By:\s*\w+\s*Env#\d+)?",
        False,
    ),
    # FILED with numeric date + time (case-sensitive for uppercase FILED)
    (
        r"FILED\s+\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M",
        False,
    ),
    # FILED with alpha month date
    (
        r"FILED\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\s+\d{1,2}\s+\d{4}",
        False,
    ),
    # FILED/IMAGED composite stamp (uppercase only)
    (r"FILED\s*/\s*IMAGED", False),
    # standalone uppercase FILED or ENTERED stamp (physical court stamp)
    (r"FILED", False),
    (r"ENTERED", False),
]


def _detect_filestamp_text(body: str) -> str:
    """Scan body for court filestamp text. Returns extracted stamp or "".

    Searches by pattern priority (e-filing > date-stamped > bare).
    All patterns are case-sensitive (uppercase FILED/ENTERED only)
    to avoid matching 'filed' in body discussion text.
    Returns the matched text (cleaned) or empty string if none found.
    """
    for pattern, ignorecase in _FILESTAMP_PATTERNS:
        flags = re.IGNORECASE if ignorecase else 0
        m = re.search(pattern, body, flags)
        if m:
            raw = m.group(0).strip()
            # Normalize whitespace
            clean = re.sub(r"\s+", " ", raw).strip()
            if len(clean) > 120:
                clean = clean[:117] + "..."
            return clean
    return ""


def _normalize_frontmatter(content: str, rel_path: Path) -> str:
    """Ensure .md file has complete, consistent frontmatter.

    Fields: original_name, virtual_path, ocr_status, filestamp, filestamp_text.
    Preserves existing values for name/path/ocr; always recomputes filestamp
    from directory (draft vs filed); detects stamp text from body.
    """
    fm_text, body = _split_frontmatter(content)

    # Parse existing frontmatter dict
    fm_fields: dict[str, str] = {}
    if fm_text:
        # Extract key: value pairs from YAML frontmatter block
        fm_block = fm_text.split("---", 2)[1] if fm_text.count("---") >= 2 else fm_text
        for line in fm_block.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, val = line.partition(":")
                fm_fields[key.strip()] = val.strip()

    # Compute defaults
    default_name = rel_path.name
    default_virtual = f"LEGAL_FILE/{rel_path}"
    # Detect OCR status from body content if not already set
    default_ocr = "good"
    if body.strip():
        clean = re.sub(r"--- Page Break ---", "", body)
        clean = re.sub(r"\s+", "", clean).strip()
        if len(clean) < 50:
            default_ocr = "image_only"
        elif len(clean) < 200:
            default_ocr = "needs_review"

    rel_str = str(rel_path)
    filestamp_bool = _compute_filestamp(rel_str)

    # Detect stamp text from body
    if rel_str.startswith("01_DRAFTS"):
        stamp_text = "draft"
    else:
        stamp_text = _detect_filestamp_text(body)
        if not stamp_text:
            stamp_text = "waiting"

    # Build complete frontmatter, preserving existing non-default values
    original_name = fm_fields.get("original_name", default_name)
    virtual_path = fm_fields.get("virtual_path", default_virtual)
    ocr_status = fm_fields.get("ocr_status", default_ocr)

    # Quote stamp_text if it contains characters that could break YAML
    if any(c in stamp_text for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "\"")):
        safe_stamp = stamp_text.replace('"', "'")
        stamp_line = f'filestamp_text: "{safe_stamp}"\n'
    else:
        stamp_line = f"filestamp_text: {stamp_text}\n"

    new_fm = (
        "---\n"
        f"original_name: {original_name}\n"
        f"virtual_path: {virtual_path}\n"
        f"ocr_status: {ocr_status}\n"
        f"filestamp: {filestamp_bool}\n"
        f"{stamp_line}"
        "---\n\n"
    )

    return new_fm + body.lstrip("\n") + "\n"


def reprocess_library(
    dry_run: bool = False, normalize: bool = False
) -> tuple[int, int]:
    """Walk REPROCESS_DIRS, re-normalize every .md body, rewrite if changed.

    Preserves original frontmatter untouched. Uses unified diff for dry-run
    preview. Returns (modified_count, error_count).
    """
    # ANSI color codes for terminal audit trail
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    modified = 0
    skipped = 0
    errors = 0
    total = 0

    for subdir in REPROCESS_DIRS:
        target_path = LEGAL_DIR / subdir
        if not target_path.exists():
            continue
        for md_file in sorted(target_path.rglob("*.md")):
            # Skip non-twin .md files (e.g. README.md, backups, docs)
            if md_file.name in ("README.md", "00_README.md"):
                continue
            if ".bak" in md_file.suffixes or md_file.name.endswith(".bak"):
                continue
            total += 1

            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception as e:
                print(f"  {RED}ERROR{RESET} reading {md_file.relative_to(LEGAL_DIR)}: {e}")
                errors += 1
                continue

            rel = md_file.relative_to(LEGAL_DIR)

            # Step 1: Normalize frontmatter (if --normalize)
            working = raw
            fm_changed = False
            if normalize:
                normed = _normalize_frontmatter(raw, rel)
                if normed != raw:
                    working = normed
                    fm_changed = True

            # Step 2: Split frontmatter + body from working content
            fm, body = _split_frontmatter(working)

            if not body.strip():
                print(f"  {YELLOW}SKIP{RESET}  {rel} (empty body)")
                skipped += 1
                continue

            # Step 3: Normalize body text
            new_body = normalize_extracted_text(body)

            # Step 4: Detect file health for reporting
            clean_body = re.sub(r"--- Page Break ---", "", body)
            clean_body = re.sub(r"\s+", "", clean_body).strip()
            body_len = len(clean_body)

            # Step 5: Stitch final result
            if new_body != body or fm_changed:
                stitched = (fm + "\n" + new_body + "\n") if fm else (new_body + "\n")
            else:
                print(f"  {CYAN}IDEM{RESET}  {rel}")
                skipped += 1
                continue

            if dry_run:
                import difflib

                old_lines = raw.splitlines(keepends=True)
                new_lines = stitched.splitlines(keepends=True)
                diff = difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=str(rel),
                    tofile=str(rel),
                    n=2,
                )
                diff_text = "".join(diff)
                if diff_text.strip():
                    print(f"\n--- {rel} ---")
                    print(diff_text.rstrip())
                print(f"  {YELLOW}WOULD_MODIFY{RESET}  {rel}")
                modified += 1
            else:
                try:
                    md_file.write_text(stitched, encoding="utf-8")
                    reason = []
                    if fm_changed:
                        reason.append("fm")
                    if new_body != body:
                        reason.append("body")
                    badge = ",".join(reason)
                    if body_len < 50:
                        status = f" {RED}[image_only]{RESET}"
                    elif body_len < 200:
                        status = f" {YELLOW}[sparse]{RESET}"
                    else:
                        status = ""
                    print(f"  {GREEN}UPDATED{RESET}  {rel} ({badge}){status}")
                    modified += 1
                except Exception as e:
                    print(f"  {RED}ERROR{RESET} writing {rel}: {e}")
                    errors += 1

    print(f"\n  {BOLD}Summary:{RESET} {total} scanned, {GREEN}{modified} modified{RESET}, "
          f"{CYAN}{skipped} skipped{RESET}, {RED}{errors} errors{RESET}")

    return modified, errors


def main():
    dry_run = "--dry-run" in sys.argv
    do_rag = "--rag" in sys.argv or "-r" in sys.argv
    do_filemap = "--filemap" in sys.argv or "-f" in sys.argv
    do_sanitize = "--sanitize" in sys.argv or "-s" in sys.argv
    auto = "--auto" in sys.argv or "-a" in sys.argv
    do_reprocess = "--reprocess" in sys.argv
    do_normalize = "--normalize" in sys.argv
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

    if "--library-report" in sys.argv:
        report_lines = []
        report_lines.append("# Library Audit Report\n")
        report_lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report_lines.append(f"| Status | File | Frontmatter | OCR | Body (chars) |\n")
        report_lines.append(f"| :--- | :--- | :--- | :--- | ---: |\n")

        counts = {"ok": 0, "fm_missing": 0, "image_only": 0, "sparse": 0, "error": 0}
        for subdir in REPROCESS_DIRS:
            dp = LEGAL_DIR / subdir
            if not dp.exists():
                continue
            for md_file in sorted(dp.rglob("*.md")):
                if md_file.name in ("README.md", "00_README.md") or ".bak" in md_file.suffixes:
                    continue
                rel = md_file.relative_to(LEGAL_DIR)
                try:
                    raw = md_file.read_text(encoding="utf-8")
                except Exception as e:
                    report_lines.append(f"| {RED}ERROR{RESET} | {rel} | read failed: {e} | - | - |\n")
                    counts["error"] += 1
                    continue

                fm_text, body = _split_frontmatter(raw)
                has_fm = bool(fm_text)

                # OCR status
                clean = re.sub(r"--- Page Break ---", "", body)
                clean = re.sub(r"\s+", "", clean).strip()
                body_len = len(clean)
                if body_len < 50:
                    ocr_tag = "image_only"
                    counts["image_only"] += 1
                elif body_len < 200:
                    ocr_tag = "sparse"
                    counts["sparse"] += 1
                elif not has_fm:
                    ocr_tag = "fm_missing"
                    counts["fm_missing"] += 1  # already counted
                else:
                    ocr_tag = "ok"
                    counts["ok"] += 1

                status_icon = {"ok": "✅", "image_only": "⚠️ ", "sparse": "🔶", "fm_missing": "📄", "error": "❌"}
                icon = status_icon.get(ocr_tag, "❓")
                fm_mark = "✅" if has_fm else "❌"
                report_lines.append(f"| {icon} | {rel} | {fm_mark} | {ocr_tag} | {body_len} |\n")

        total = sum(counts.values())
        report_lines.append(f"\n## Summary\n")
        report_lines.append(f"- **Total files:** {total}\n")
        report_lines.append(f"- **OK:** {counts['ok']}\n")
        report_lines.append(f"- **Missing frontmatter:** {counts['fm_missing']}\n")
        report_lines.append(f"- **Image-only (needs OCR):** {counts['image_only']}\n")
        report_lines.append(f"- **Sparse text:** {counts['sparse']}\n")
        report_lines.append(f"- **Errors:** {counts['error']}\n")

        report_path = CASE_DIR / "LIBRARY_AUDIT.md"
        report_path.write_text("".join(report_lines), encoding="utf-8")
        print(f"\nLibrary audit written to {report_path.relative_to(Path.cwd())}")
        print(f"  {total} files, {counts['ok']} ok, {counts['fm_missing']} missing fm, "
              f"{counts['image_only']} image-only, {counts['sparse']} sparse, {counts['error']} errors")
        return

    if do_reprocess:
        modified, errors = reprocess_library(dry_run=dry_run, normalize=do_normalize)
        return

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


# ── Date extraction & processing tracker ──


def track_ingestion(legal_dir: Path = LEGAL_DIR, case_dir: Path = CASE_DIR) -> int:
    """Post-ingestion tracking: extract dates, cross-reference, write UNPROCESSED.md.
    Returns number of files not yet date-indexed."""
    print(f"\n{'=' * 72}")
    print(f"  STAGE: Date extraction & processing tracker")
    print(f"{'=' * 72}")

    # ── Step 1: Run extract_all_dates.py ──
    date_index_path = case_dir / "DATE_INDEX.md"
    print(f"\n  [1/3] Running extract_all_dates.py ...")
    try:
        subprocess.run(
            ["uv", "run", str(EXTRACT_DATES_SCRIPT),
             str(case_dir), "--output", str(date_index_path)],
            capture_output=True, text=True, timeout=300, check=True,
        )
        print(f"    DATE_INDEX.md regenerated ({date_index_path})")
    except subprocess.CalledProcessError as e:
        print(f"    extract_all_dates.py failed: {e.stderr.strip()}", file=sys.stderr)
        return -1
    except Exception as e:
        print(f"    extract_all_dates.py error: {e}", file=sys.stderr)
        return -1

    # ── Step 2: Parse DATE_INDEX.md to get indexed files ──
    print(f"  [2/3] Cross-referencing LEGAL_FILE vs DATE_INDEX ...")
    content = date_index_path.read_text(encoding="utf-8")

    # Extract file paths from "Files by Date Count" table and "Full Date Index" sections
    indexed_files = set()
    for m in re.finditer(r"^\| \d+ \| (.+?) \|$", content, re.MULTILINE):
        fpath = m.group(1).strip()
        # Skip non-LEGAL_FILE entries
        if fpath.startswith("LEGAL_FILE/"):
            # Normalize: remove leading LEGAL_FILE/
            indexed_files.add(fpath)

    # Also find all files from "Full Date Index" sections (### headers)
    for m in re.finditer(r"^### (.+)$", content, re.MULTILINE):
        fpath = m.group(1).strip()
        if fpath.startswith("LEGAL_FILE/"):
            indexed_files.add(fpath)

    indexed_rel = set()
    for f in indexed_files:
        # Strip "LEGAL_FILE/" prefix -> relative to LEGAL_FILE dir
        rel = f.replace("LEGAL_FILE/", "", 1)
        indexed_rel.add(rel)

    # ── Step 3: Scan LEGAL_FILE for all .md files ──
    actual_files = set()
    for f in sorted(legal_dir.rglob("*.md")):
        rel = str(f.relative_to(legal_dir))
        actual_files.add(rel)

    # Also check for .pdf files without .md twins (orphan PDFs)
    orphan_pdfs = []
    for f in sorted(legal_dir.rglob("*.pdf")):
        md_twin = f.with_suffix(".md")
        if not md_twin.exists():
            rel = str(f.relative_to(legal_dir))
            orphan_pdfs.append(rel)

    unprocessed = sorted(actual_files - indexed_rel)
    processed = sorted(actual_files & indexed_rel)

    print(f"\n    LEGAL_FILE .md files:     {len(actual_files)}")
    print(f"    Indexed in DATE_INDEX:   {len(processed)}")
    print(f"    NOT yet date-indexed:    {len(unprocessed)}")
    if orphan_pdfs:
        print(f"    Orphan PDFs (no .md twin): {len(orphan_pdfs)}")

    # ── Step 4: Write UNPROCESSED.md ──
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"# Ingestion Processing Status — {case_dir.name}")
    lines.append(f"Generated: {now}")
    lines.append(f"")
    lines.append(f"| Category | Count |")
    lines.append(f"|----------|-------|")
    lines.append(f"| Date-indexed files | {len(processed)} |")
    lines.append(f"| **Not yet date-indexed** | **{len(unprocessed)}** |")
    lines.append(f"| Orphan PDFs (no .md twin) | {len(orphan_pdfs)} |")
    lines.append(f"")

    if unprocessed:
        lines.append(f"## Files Not Yet Date-Indexed ({len(unprocessed)})")
        lines.append(f"These .md files were not found in DATE_INDEX.md.")
        lines.append(f"Run `extract_all_dates.py` then manually review for timeline events.")
        lines.append(f"")
        for f in unprocessed:
            lines.append(f"- `LEGAL_FILE/{f}`")
        lines.append(f"")

    if orphan_pdfs:
        lines.append(f"## Orphan PDFs — No .md Twin ({len(orphan_pdfs)})")
        lines.append(f"These PDFs have no digital twin. Run `sync_legal_docs.py` on them.")
        lines.append(f"")
        for f in orphan_pdfs:
            lines.append(f"- `LEGAL_FILE/{f}`")
        lines.append(f"")

    if processed:
        lines.append(f"## Already Date-Indexed ({len(processed)})")
        lines.append(f"These files appear in DATE_INDEX.md. Verify timeline events are extracted.")
        lines.append(f"")
        for f in processed:
            lines.append(f"- `LEGAL_FILE/{f}`")
        lines.append(f"")

    report_path = case_dir / "UNPROCESSED.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n    Written: UNPROCESSED.md")

    print(f"\n{'=' * 72}\n")
    return len(unprocessed)


# ── Unscanned report ──


def report_unscanned(legal_dir: Path = LEGAL_DIR, write_file: bool = True) -> int:
    """Scan all .md twins in LEGAL_FILE and report image-only / low-text files.
    Writes OCR_REPORT.md to case dir when write_file=True.
    Returns count of files needing attention."""
    image_only = []
    needs_review = []
    for f in sorted(legal_dir.rglob("*.md")):
        body, ocr_status = extract_raw_text(f)
        if not body.strip():
            ocr_status = "image_only"
        else:
            ocr_status = _detect_ocr_quality(body, ocr_status)

        rel = f.relative_to(legal_dir.parent)
        if ocr_status == "image_only":
            image_only.append(rel)
        elif ocr_status == "needs_review":
            needs_review.append(rel)

    total = len(image_only) + len(needs_review)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# OCR Quality Report — {legal_dir.parent.name}/LEGAL_FILE/")
    lines.append(f"Generated: {now}")
    lines.append(f"")
    lines.append(f"| Status | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Image Only | {len(image_only)} |")
    lines.append(f"| Needs Review | {len(needs_review)} |")
    lines.append(f"| **Total** | **{total}** |")
    lines.append(f"")

    if image_only:
        lines.append(f"## Image Only ({len(image_only)})")
        lines.append(f"No text could be extracted. Requires AI Vision OCR (Gemini).")
        lines.append(f"")
        for f in image_only:
            lines.append(f"- `{f}`")
        lines.append(f"")

    if needs_review:
        lines.append(f"## Needs Review ({len(needs_review)})")
        lines.append(f"Very low text content — may have partial OCR or be mostly image.")
        lines.append(f"")
        for f in needs_review:
            lines.append(f"- `{f}`")
        lines.append(f"")

    if not total:
        lines.append(f"All files have readable text.")

    report_text = "\n".join(lines)

    # Always print to stdout
    print(f"\n{'=' * 72}")
    print(f"  OCR QUALITY REPORT — {legal_dir.parent.name}/LEGAL_FILE/")
    print(f"{'=' * 72}")

    if image_only:
        print(f"\n  IMAGE ONLY — {len(image_only)} file(s) — no text extracted")
        print(f"  {'─' * 60}")
        for f in image_only:
            print(f"    {f}")
    else:
        print(f"\n  No image-only files found.")

    if needs_review:
        print(f"\n  NEEDS REVIEW — {len(needs_review)} file(s) — very low text")
        print(f"  {'─' * 60}")
        for f in needs_review:
            print(f"    {f}")
    else:
        print(f"\n  No low-text files found.")

    print(f"\n  TOTAL: {len(image_only)} image-only + {len(needs_review)} needs review")
    print(f"{'=' * 72}")

    if write_file:
        report_path = legal_dir.parent / "OCR_REPORT.md"
        report_path.write_text(report_text + "\n", encoding="utf-8")
        print(f"  Written: {report_path.relative_to(Path.cwd().resolve())}")

    print()
    return total


if __name__ == "__main__":
    if "--report-unscanned" in sys.argv or "-u" in sys.argv:
        report_unscanned()
    elif "--track" in sys.argv or "-t" in sys.argv:
        track_ingestion()
    else:
        main()
