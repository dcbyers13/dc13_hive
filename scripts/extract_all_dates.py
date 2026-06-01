#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Extract all dates from case documents and build a master date index.

Scans .md, .txt, .json files in a directory tree, extracts date patterns
and surrounding context, and outputs a structured report.

Usage:
    uv run extract_all_dates.py <directory> [--output <path>] [--min-year 2012]

Output:
    A markdown report with:
    - Summary stats (total dates found, per-file breakdown)
    - Full date index grouped by file
    - Year histogram
    - All unique events (sentences near dates)
"""

import os
import re
import sys
import json
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime


# --- Date patterns ---

DATE_PATTERNS = [
    # ISO: 2024-01-15
    (r'\b(\d{4}-\d{1,2}-\d{1,2})\b', '%Y-%m-%d'),
    # US: 01/15/2024 or 1/15/2024
    (r'\b(\d{1,2}/\d{1,2}/\d{4})\b', '%m/%d/%Y'),
    # US: 01/15/24
    (r'\b(\d{1,2}/\d{1,2}/\d{2})\b', '%m/%d/%y'),
    # Written: January 15, 2024 or Jan 15, 2024
    (r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b', None),
    # Written: 15 January 2024
    (r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b', None),
]

# Context extraction: grab the sentence containing the date
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
# Case number pattern (to exclude from dates)
CASE_NUM_RE = re.compile(r'\b\d{2,4}[A-Z]{2}\d{5,12}\b')
# Docket-style date prefix in filenames
FILENAME_DATE_RE = re.compile(
    r'(\d{4}[-_]\d{2}[-_]\d{2}|\d{4}_\d{2}_\d{2}|\d{4}-\d{2}-\d{2})'
)
FILENAME_4DIGIT_YEAR = re.compile(r'\b(19\d{2}|20\d{2})\b')


def parse_date(date_str: str, pattern: tuple) -> datetime | None:
    """Try to parse a date string into a datetime object."""
    regex, fmt = pattern
    try:
        if fmt:
            return datetime.strptime(date_str, fmt)
        else:
            # Written dates: try multiple formats
            cleaned = date_str.replace('.', '').replace(',', '')
            for f in ['%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y']:
                try:
                    return datetime.strptime(cleaned, f)
                except ValueError:
                    continue
    except (ValueError, OverflowError):
        pass
    return None


def extract_dates_from_text(text: str, min_year: int = 2012) -> list[dict]:
    """
    Extract all dates from text with surrounding context.

    Returns list of {date_str, parsed_date, context, match_type}
    """
    results = []
    seen = set()  # dedup (date_str, context[:60])

    # Remove case numbers that look like dates
    text = CASE_NUM_RE.sub('', text)

    # Split into sentences for context
    sentences = SENTENCE_SPLIT.split(text)

    for sentence in sentences:
        if not sentence.strip():
            continue
        for pattern in DATE_PATTERNS:
            for match in re.finditer(pattern[0], sentence, re.IGNORECASE):
                date_str = match.group(1)
                parsed = parse_date(date_str, pattern)
                if parsed is None:
                    continue
                if parsed.year < min_year or parsed.year > 2030:
                    continue

                key = (date_str, sentence[:80].strip())
                if key in seen:
                    continue
                seen.add(key)

                # Clean up context
                ctx = sentence.strip()
                if len(ctx) > 300:
                    ctx = ctx[:297] + '...'

                results.append({
                    'date_str': date_str,
                    'year': parsed.year,
                    'month': parsed.month,
                    'day': parsed.day,
                    'iso': parsed.strftime('%Y-%m-%d'),
                    'context': ctx,
                })
                break  # one date per sentence per pattern

    return results


def extract_dates_from_json(file_path: Path, min_year: int) -> list[dict]:
    """
    Extract dates from SMS JSON export (Violette_Final_Timeline_With_Assets.json format).
    """
    results = []
    try:
        data = json.loads(file_path.read_text(encoding='utf-8'))
        if isinstance(data, list):
            for entry in data:
                ts = entry.get('timestamp', '')
                msg = entry.get('message', '')
                sender = entry.get('sender', '')
                attachment = entry.get('attachment', '')

                # Try parsing the timestamp
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                    try:
                        parsed = datetime.strptime(ts, fmt)
                        if parsed.year >= min_year:
                            ctx = f"[{sender}] {msg[:200]}"
                            if attachment:
                                ctx += f" [att:{attachment}]"
                            results.append({
                                'date_str': parsed.strftime('%Y-%m-%d'),
                                'year': parsed.year,
                                'month': parsed.month,
                                'day': parsed.day,
                                'iso': parsed.strftime('%Y-%m-%d'),
                                'context': ctx,
                                'source_type': 'sms',
                            })
                        break
                    except ValueError:
                        continue

                # Also extract dates from message content
                if msg:
                    content_dates = extract_dates_from_text(msg, min_year)
                    for d in content_dates:
                        d['source_type'] = 'sms_content'
                        d['context'] = f"[{sender}] {d['context']}"
                        results.append(d)
    except (json.JSONDecodeError, Exception):
        pass

    return results


def extract_dates_from_filename(file_path: Path, rel_root: Path) -> list[dict]:
    """Extract dates embedded in the filename itself."""
    results = []
    fname = str(file_path.relative_to(rel_root))

    for match in FILENAME_DATE_RE.finditer(fname):
        raw = match.group(1)
        cleaned = raw.replace('_', '-')
        try:
            parsed = datetime.strptime(cleaned, '%Y-%m-%d')
            results.append({
                'date_str': parsed.strftime('%Y-%m-%d'),
                'year': parsed.year,
                'month': parsed.month,
                'day': parsed.day,
                'iso': parsed.strftime('%Y-%m-%d'),
                'context': f"[from filename: {file_path.name}]",
                'source_type': 'filename',
            })
        except ValueError:
            pass

    return results


def scan_directory(
    directory: Path, min_year: int = 2012
) -> dict[str, dict]:
    """
    Scan all documents and return date index.

    Returns dict:
        file_rel_path -> {
            'dates': list[dict],
            'filename_dates': list[dict],
            'file_type': str,
            'date_count': int,
        }
    """
    index = {}

    # File types to scan
    text_extensions = {'.md', '.txt', '.json', '.html'}

    for root, dirs, files in os.walk(directory):
        # Skip hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for fname in files:
            if fname.startswith('.'):
                continue

            ext = Path(fname).suffix.lower()
            if ext not in text_extensions:
                continue

            fp = Path(root) / fname
            rel = str(fp.relative_to(directory))

            entry = {
                'dates': [],
                'filename_dates': [],
                'file_type': ext,
                'date_count': 0,
            }

            # 1. Dates from filename
            entry['filename_dates'] = extract_dates_from_filename(fp, directory)

            # 2. Dates from content
            try:
                content = fp.read_text(encoding='utf-8', errors='replace')
            except Exception:
                continue

            if ext == '.json':
                entry['dates'] = extract_dates_from_json(fp, min_year)
            else:
                entry['dates'] = extract_dates_from_text(content, min_year)

            if entry['dates'] or entry['filename_dates']:
                entry['date_count'] = len(entry['dates']) + len(entry['filename_dates'])
                index[rel] = entry

    return index


def year_histogram(index: dict) -> Counter:
    """Build year histogram from all dates."""
    hist = Counter()
    for entry in index.values():
        for d in entry['dates']:
            hist[d['year']] += 1
        for d in entry['filename_dates']:
            hist[d['year']] += 1
    return hist


def generate_report(index: dict, directory: Path) -> str:
    """Generate a markdown report from the date index."""
    lines = []
    total_files = len(index)
    total_dates = sum(e['date_count'] for e in index.values())
    hist = year_histogram(index)

    lines.append(f"# Date Extraction Report")
    lines.append(f"")
    lines.append(f"**Source:** `{directory}`")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")
    lines.append(f"## Summary")
    lines.append(f"")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Files with dates | {total_files} |")
    lines.append(f"| Total dates found | {total_dates} |")
    lines.append(f"")
    lines.append(f"## Year Histogram")
    lines.append(f"")
    lines.append(f"| Year | Count |")
    lines.append(f"|------|-------|")
    for year in sorted(hist):
        lines.append(f"| {year} | {hist[year]} |")
    lines.append("")

    lines.append(f"## Files by Date Count")
    lines.append(f"")
    lines.append(f"| Date Count | File |")
    lines.append(f"|------------|------|")
    for rel in sorted(index, key=lambda r: index[r]['date_count'], reverse=True)[:50]:
        lines.append(f"| {index[rel]['date_count']} | {rel} |")
    lines.append("")

    lines.append("## Full Date Index")
    lines.append("")
    for rel in sorted(index):
        entry = index[rel]
        lines.append(f"### {rel}")
        lines.append(f"")
        lines.append(f"**Total:** {entry['date_count']} dates | **Type:** {entry['file_type']}")
        lines.append("")

        if entry['filename_dates']:
            lines.append("**From filename:**")
            for d in entry['filename_dates']:
                lines.append(f"- {d['iso']}")
            lines.append("")

        if entry['dates']:
            lines.append("| Date | Context |")
            lines.append("|------|---------|")
            for d in entry['dates']:
                ctx = d.get('context', '').replace('\n', ' ')[:120]
                lines.append(f"| {d['iso']} | {ctx} |")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    directory = Path(sys.argv[1]).resolve()
    if not directory.is_dir():
        print(f"Error: not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    min_year = 2012
    output_path = None

    for i, arg in enumerate(sys.argv[2:], start=2):
        if arg == '--min-year' and i + 1 < len(sys.argv):
            min_year = int(sys.argv[i + 1])
        elif arg == '--output' and i + 1 < len(sys.argv):
            output_path = sys.argv[i + 1]

    print(f"Scanning:   {directory}")
    print(f"Min year:   {min_year}")
    print()

    index = scan_directory(directory, min_year)

    report = generate_report(index, directory)

    if output_path:
        Path(output_path).write_text(report, encoding='utf-8')
        print(f"Report saved: {output_path}")
    else:
        print(report[:2000])
        print(f"\n... ({len(report)} chars total)")

    total_dates = sum(e['date_count'] for e in index.values())
    print(f"\nFiles with dates: {len(index)}")
    print(f"Total dates found: {total_dates}")


if __name__ == '__main__':
    main()
