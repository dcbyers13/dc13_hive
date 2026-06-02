#!/usr/bin/env python3
"""
Build a neutral, chronological master timeline from TIMELINE.md.
Parses all table rows from main sections, sorts chronologically,
strips advocacy language, and generates TIMELINE_MASTER.md.
"""

import re

INPUT = "/Users/macuser/LAW_LAB/25FA152/TIMELINE.md"
OUTPUT = "/Users/macuser/LAW_LAB/25FA152/TIMELINE_MASTER.md"

SECTION_LABEL_MAP = {
    "2012\u20132015": "2012\u20132015",
    "2016\u20132020": "2016\u20132020",
    "2021\u20132026": "2021\u20132026",
    "Criminal Cases (David C. Byers - DCB)": "Criminal Cases (DCB)",
    "Criminal Cases (Pauletta Donatello - PDD)": "Criminal Cases (PDD)",
    "Criminal Cases (Cory Michael Neill - CMN)": "Criminal Cases (CMN)",
}

SKIP_SECTIONS = {
    "Third-Party Influence Timeline",
    "Mental Health Timeline",
    "Communication Breakdown Log",
}

CRIMINAL_SECTIONS = {
    "Criminal Cases (David C. Byers - DCB)",
    "Criminal Cases (Pauletta Donatello - PDD)",
    "Criminal Cases (Cory Michael Neill - CMN)",
}


def normalize_header(text):
    """Normalize a section header for comparison."""
    return text.strip().lower()


def parse_date_sortkey(raw):
    """
    Return a sortable tuple (year, month, precision, day).
    precision: 0=full, 1=month-year, 2=year-only, 3=vague/range
    """
    s = raw.strip()

    # Date range → use start
    m = re.match(r"^(\d{4}(?:-\d{2}(?:-\d{2})?)?)\s+to\s+", s)
    if m:
        s = m.group(1)

    # "onward" suffix
    s = re.sub(r"\s+onward.*", "", s)

    # "Summer YYYY"
    m = re.match(r"^Summer\s+(\d{4})$", s, re.IGNORECASE)
    if m:
        return (int(m.group(1)), 7, 3, 1)

    # YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), 0, int(m.group(3)))

    # YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), 1, 0)

    # YYYY
    m = re.match(r"^(\d{4})$", s)
    if m:
        return (int(m.group(1)), 1, 2, 0)

    return (9999, 99, 99, 99)


def strip_markup(text):
    """Remove bold/italic markers but keep the text."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    return text.strip()


def event_normalized(text):
    """Normalize event text for dedup comparison."""
    return strip_markup(text).strip().lower().rstrip(". ")


def event_short_key(text, length=80):
    """First N chars of normalized text as a dedup key."""
    return event_normalized(text)[:length]


def event_core_tokens(text):
    """Extract core tokens for similarity matching."""
    t = event_normalized(text)
    t = re.sub(r"[^a-z0-9\s]", "", t)
    tokens = set(t.split())
    # Remove very common words
    stopwords = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "was",
        "are",
        "were",
        "has",
        "have",
        "had",
        "been",
        "being",
        "be",
        "not",
        "no",
    }
    return tokens - stopwords


def extract_case_numbers(text):
    """Extract case numbers like (22CM913) or (18CF901) from event text."""
    return set(re.findall(r"(?<![a-zA-Z])(\d{2,3}[A-Z]{2,5}\d{1,4})(?![a-zA-Z])", text))


def jaccard_similarity(a, b):
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def events_are_same_incident(a_text, b_text):
    """Check if two event descriptions refer to the same incident."""
    # Shared case number is strong evidence
    a_cases = extract_case_numbers(a_text)
    b_cases = extract_case_numbers(b_text)
    if a_cases & b_cases:
        return True
    # Fall back to Jaccard similarity on core tokens
    tok_a = event_core_tokens(a_text)
    tok_b = event_core_tokens(b_text)
    return jaccard_similarity(tok_a, tok_b) >= 0.50


def build_timeline():
    with open(INPUT, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_main = ""
    current_sub = ""
    skip_section = False
    all_rows = []

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("#"):
            level = (
                2
                if stripped.startswith("## ")
                else 3
                if stripped.startswith("### ")
                else None
            )
            if level == 2:
                raw_header = stripped.lstrip("#").strip()
                current_main = raw_header
                current_sub = ""
                skip_section = any(
                    normalize_header(current_main).startswith(normalize_header(s))
                    for s in SKIP_SECTIONS
                )
                continue
            elif level == 3:
                current_sub = stripped.lstrip("#").strip()
                continue
            else:
                continue

        if skip_section:
            continue

        # Only process table data rows (lines starting with |)
        if not stripped.startswith("|"):
            continue

        # Skip separator rows
        if "|--" in stripped:
            continue

        # Skip header row
        if "Date" in stripped and "Event" in stripped and "Category" in stripped:
            continue

        # Parse pipe-delimited row
        parts = [p.strip() for p in stripped.split("|")]

        # Expect at least 6 parts (leading empty, date, event, category, docs, notes)
        if len(parts) < 6:
            continue

        date_str = parts[1]
        event_text = parts[2]
        supporting_docs = parts[4]

        if not date_str or not event_text:
            continue

        # Build source section label
        label = SECTION_LABEL_MAP.get(current_main, current_main)
        if current_sub:
            # Map subsection to a clean label
            sub_clean = re.sub(r"^#{1,3}\s*", "", current_sub).strip()
            label = f"{label} \u2014 {sub_clean}"

        sort_key = parse_date_sortkey(date_str)

        all_rows.append(
            {
                "date_raw": date_str,
                "event_raw": event_text,
                "docs_raw": supporting_docs,
                "section": label,
                "sort_key": sort_key,
            }
        )

    # ── Merge phase 1: exact match on (date, short event key) ──
    merged = {}
    for row in all_rows:
        key = (row["date_raw"], event_short_key(row["event_raw"]))
        if key in merged:
            existing = merged[key]
            _merge_into(existing, row)
        else:
            row["sections"] = [row["section"]]
            merged[key] = row

    # ── Merge phase 2: same date, similar event text ──
    by_date = {}
    for key, row in merged.items():
        by_date.setdefault(row["date_raw"], []).append(row)

    final = []
    for date, rows in by_date.items():
        used = [False] * len(rows)
        for i in range(len(rows)):
            if used[i]:
                continue
            base = rows[i]
            for j in range(i + 1, len(rows)):
                if used[j]:
                    continue
                if events_are_same_incident(base["event_raw"], rows[j]["event_raw"]):
                    _merge_into(base, rows[j])
                    used[j] = True
            final.append(base)

    # Sort by chronological key
    final.sort(key=lambda r: r["sort_key"])

    # Strip advocacy language from event text
    for row in final:
        row["event_clean"] = strip_markup(row["event_raw"])

    # ── Write output ──
    out_lines = []
    out_lines.append("# Master Timeline: Byers v. Donatello (25FA152)")
    out_lines.append("")
    out_lines.append("Chronological compilation of all documented events")
    out_lines.append("")
    out_lines.append("| Date | Event | Source Section(s) | Supporting Documents |")
    out_lines.append("|------|-------|-------------------|---------------------|")

    for row in final:
        date_col = row["date_raw"]
        event_col = row["event_clean"].replace("|", "\\|")
        sections_col = ", ".join(sorted(set(row["sections"]))).replace("|", "\\|")

        docs = row["docs_raw"].strip()
        if not docs or docs == "(N/A)":
            docs_col = "(N/A)"
        else:
            docs_col = docs.replace("|", "\\|")

        out_lines.append(f"| {date_col} | {event_col} | {sections_col} | {docs_col} |")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    print(f"Master timeline written to {OUTPUT}")
    print(f"Total events: {len(final)}")


def _clean_doc_path(path):
    """Strip markup from a document path for dedup comparison."""
    return strip_markup(path)


def _merge_into(base, other):
    """Merge fields from `other` row into `base` row."""
    # Merge sections
    for s in other.get("sections", [other["section"]]):
        if "sections" not in base:
            base["sections"] = [base["section"]]
        if s not in base["sections"]:
            base["sections"].append(s)

    # Merge supporting documents (strip markup before dedup)
    existing_docs = {}
    if base["docs_raw"] and base["docs_raw"] != "(N/A)":
        for d in base["docs_raw"].split(","):
            cleaned = _clean_doc_path(d.strip())
            existing_docs[cleaned] = d.strip()
    new_docs = {}
    if other["docs_raw"] and other["docs_raw"] != "(N/A)":
        for d in other["docs_raw"].split(","):
            cleaned = _clean_doc_path(d.strip())
            new_docs[cleaned] = d.strip()
    all_docs = {}
    for k, v in existing_docs.items():
        all_docs[k] = v
    for k, v in new_docs.items():
        if k not in all_docs:
            all_docs[k] = v
    base["docs_raw"] = ", ".join(sorted(all_docs.values())) if all_docs else "(N/A)"

    # Use longer event description (more complete)
    if len(other["event_raw"]) > len(base["event_raw"]):
        base["event_raw"] = other["event_raw"]


if __name__ == "__main__":
    build_timeline()
