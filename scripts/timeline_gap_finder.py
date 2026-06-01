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
# dependencies = [
#     "markdown",
#     "beautifulsoup4",
# ]
# ///

"""
Cross-reference TIMELINE.md against the full document date index.

Finds:
- Dates in documents not yet in the timeline
- Sparse periods (gaps > 3 months with no timeline events)
- Documents with dates but no timeline entries (candidate for new events)
- High-density document sources (SMS, TalkingParents) that may contain
  discoverable communication-pattern events

Usage:
    uv run timeline_gap_finder.py <case_dir>

Expects:
    <case_dir>/TIMELINE.md      — The existing 5-column timeline
    <case_dir>/DATE_INDEX.md    — Output from extract_all_dates.py
"""

import re
import sys
import markdown
from pathlib import Path
from bs4 import BeautifulSoup
from collections import defaultdict, Counter
from datetime import datetime, timedelta


def parse_timeline_events(timeline_path: Path) -> list[dict]:
    """
    Parse existing TIMELINE.md and return all events with dates.

    Supports the 5-column format:
    | Date | Event/Incident | Category | Supporting Document(s) | Notes |
    """
    content = timeline_path.read_text(encoding='utf-8')
    events = []
    current_section = None

    html = markdown.markdown(content, extensions=['tables'])
    soup = BeautifulSoup(html, 'html.parser')

    for el in soup.find_all():
        if el.name in ('h1', 'h2', 'h3', 'h4'):
            current_section = el.get_text().strip()
        elif el.name == 'table':
            rows = el.find_all('tr')
            if len(rows) >= 2:
                for row in rows[1:]:  # skip header
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        date_text = cells[0].get_text().strip()
                        event_text = cells[1].get_text().strip()

                        # Parse date
                        parsed = None
                        for fmt in ['%Y-%m-%d', '%Y', '%m/%d/%Y']:
                            try:
                                parsed = datetime.strptime(date_text, fmt)
                                break
                            except ValueError:
                                continue

                        if parsed:
                            events.append({
                                'section': current_section,
                                'date_raw': date_text,
                                'date': parsed,
                                'event': event_text[:120],
                            })

    return events


def parse_date_index(index_path: Path) -> dict:
    """
    Parse the DATE_INDEX.md report and extract per-file date lists.

    Returns: {file_rel_path: [date_str, ...]}
    """
    content = index_path.read_text(encoding='utf-8')
    file_dates = defaultdict(list)
    current_file = None

    for line in content.split('\n'):
        # Section header = filename
        h3 = re.match(r'^### (.+)$', line)
        if h3:
            current_file = h3.group(1).strip()
        # Date row in table
        elif current_file and '|' in line and line.strip().startswith('| '):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if len(cells) >= 2:
               # Try to match ISO date
                date_match = re.match(r'^(\d{4}-\d{2}-\d{2})$', cells[0])
                if date_match:
                    file_dates[current_file].append(date_match.group(1))

    return dict(file_dates)


def find_gaps(timeline_events: list[dict], max_gap_days: int = 90) -> list[dict]:
    """Find periods with no timeline events longer than max_gap_days."""
    if not timeline_events:
        return []

    sorted_dates = sorted(set(e['date'] for e in timeline_events))
    gaps = []

    for i in range(len(sorted_dates) - 1):
        gap = (sorted_dates[i + 1] - sorted_dates[i]).days
        if gap > max_gap_days:
            gaps.append({
                'from': sorted_dates[i],
                'to': sorted_dates[i + 1],
                'gap_days': gap,
                'from_str': sorted_dates[i].strftime('%Y-%m-%d'),
                'to_str': sorted_dates[i + 1].strftime('%Y-%m-%d'),
            })

    return gaps


def generate_report(
    case_dir: Path,
    timeline_events: list[dict],
    date_index: dict,
    gaps: list[dict],
) -> str:
    """Generate an actionable gap analysis report."""
    lines = []
    timeline_dates = set()
    for e in timeline_events:
        timeline_dates.add(e['date'].strftime('%Y-%m-%d'))
        if e['date_raw'] != e['date'].strftime('%Y-%m-%d'):
            # Also add partial-year dates like "2012"
            timeline_dates.add(e['date_raw'])

    # All unique document dates (flatten)
    doc_dates = set()
    doc_date_to_files = defaultdict(list)
    for fname, dates in date_index.items():
        for d in dates:
            doc_dates.add(d)
            doc_date_to_files[d].append(fname)

    # Dates in docs but not timeline (potential new events)
    missing_dates = sorted(doc_dates - timeline_dates)

    # Files with dates but NO timeline events matching any of their dates
    files_without_events = []
    for fname, dates in sorted(date_index.items(), key=lambda x: len(x[1]), reverse=True):
        if not any(d in timeline_dates for d in dates):
            files_without_events.append((fname, len(dates)))

    # Year density comparison
    doc_year_counts = Counter()
    timeline_year_counts = Counter()
    for d in doc_dates:
        try:
            doc_year_counts[int(d[:4])] += 1
        except (ValueError, IndexError):
            pass
    for e in timeline_events:
        timeline_year_counts[e['date'].year] += 1

    lines.append("# Timeline Gap Analysis Report")
    lines.append("")
    lines.append(f"**Case:** `{case_dir}`")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Timeline events | {len(timeline_events)} |")
    lines.append(f"| Unique dates in documents | {len(doc_dates)} |")
    lines.append(f"| Dates in documents NOT in timeline | {len(missing_dates)} |")
    lines.append(f"| Documents with dates but no timeline match | {len(files_without_events)} |")
    lines.append(f"| Timeline gaps (>90 days) | {len(gaps)} |")
    lines.append("")

    lines.append("## Year Density (docs vs timeline)")
    lines.append("")
    lines.append("| Year | Doc Dates | Timeline Events | Delta |")
    lines.append("|------|-----------|-----------------|-------|")
    all_years = sorted(set(doc_year_counts.keys()) | set(timeline_year_counts.keys()))
    for yr in all_years:
        dc = doc_year_counts.get(yr, 0)
        tc = timeline_year_counts.get(yr, 0)
        delta = dc - tc
        marker = " ⚠️" if delta > 0 and tc == 0 else ""
        lines.append(f"| {yr} | {dc} | {tc} | {delta:+d}{marker} |")
    lines.append("")

    if gaps:
        lines.append("## Timeline Gaps (>90 days)")
        lines.append("")
        lines.append("| From | To | Gap (days) |")
        lines.append("|------|----|------------|")
        for g in gaps:
            lines.append(f"| {g['from_str']} | {g['to_str']} | {g['gap_days']} |")
        lines.append("")
        lines.append("**Sections affected by gaps:**")
        for g in gaps[:5]:
            # Find events near this gap
            nearby = [e for e in timeline_events
                      if g['from'] - timedelta(days=30) <= e['date'] <= g['to'] + timedelta(days=30)]
            sections = set(e['section'] for e in nearby if e['section'])
            if sections:
                lines.append(f"- {g['from_str']} to {g['to_str']}: {', '.join(sorted(sections))}")
        lines.append("")

    lines.append("## High-Value Document Sources (dates not in timeline)")
    lines.append("")
    lines.append("These documents have many dates, but few/none of those dates appear in TIMELINE.md.")
    lines.append("They are strong candidates for timeline enrichment.")
    lines.append("")
    lines.append("| File | Document Dates |")
    lines.append("|------|----------------|")
    for fname, count in files_without_events[:20]:
        lines.append(f"| {count} | {fname} |")
    lines.append("")

    # Sample missing dates from top sources
    lines.append("## Sample Missing Dates (from top documents)")
    lines.append("")
    lines.append("These dates appear in documents but aren't in the timeline yet.")
    lines.append("")
    seen_samples = 0
    for fname, _ in files_without_events[:5]:
        dates = date_index.get(fname, [])
        sample = [d for d in dates if d not in timeline_dates][:10]
        if sample:
            lines.append(f"### {fname}")
            lines.append("")
            for d in sample:
                # Find a context snippet from DATE_INDEX
                lines.append(f"- {d}")
            lines.append("")
            seen_samples += 1

    lines.append("---")
    lines.append("")
    lines.append("*Generated by timeline_gap_finder.py*")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    case_dir = Path(sys.argv[1]).resolve()
    timeline_path = case_dir / "TIMELINE.md"
    index_path = case_dir / "DATE_INDEX.md"

    if not timeline_path.exists():
        print(f"Error: TIMELINE.md not found in {case_dir}", file=sys.stderr)
        sys.exit(1)
    if not index_path.exists():
        print(f"Error: DATE_INDEX.md not found. Run extract_all_dates.py first.", file=sys.stderr)
        sys.exit(1)

    print("Parsing TIMELINE.md...")
    timeline_events = parse_timeline_events(timeline_path)
    print(f"  Found {len(timeline_events)} events")

    print("Parsing DATE_INDEX.md...")
    date_index = parse_date_index(index_path)
    print(f"  Found {sum(len(v) for v in date_index.values())} document dates across {len(date_index)} files")

    print("Analyzing gaps...")
    gaps = find_gaps(timeline_events, max_gap_days=90)
    print(f"  Found {len(gaps)} gaps > 90 days")

    print("Generating report...\n")
    report = generate_report(case_dir, timeline_events, date_index, gaps)

    output_path = case_dir / "TIMELINE_GAP_ANALYSIS.md"
    output_path.write_text(report, encoding='utf-8')
    print(f"Report saved: {output_path}")


if __name__ == '__main__':
    main()
