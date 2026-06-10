#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "pyyaml",
# ]
# ///

"""
Fetch Illinois appellate opinions and write them as .md digital twins to CASE_LAW/.

Targets the CourtListener REST API for full-text retrieval, then falls back to
a validated skeleton with a ## Manual Append Required placeholder (for Rule 23
orders and other un-paywalled opinions).

Usage:
    uv run dc13_hive/scripts/fetch_case_law.py --cite "376 Ill. App. 3d 269"
    uv run dc13_hive/scripts/fetch_case_law.py --cite "2023 IL App (1st) 221103-U" --no-fetch
    uv run dc13_hive/scripts/fetch_case_law.py --batch-file cases.txt
    uv run dc13_hive/scripts/fetch_case_law.py --cite "376 Ill. App. 3d 269" --output-dir CASE_LAW

Batch file format (one case per line, tab-separated):
    citation\tcase_name\tyear\tjurisdiction\tcore_holding\tstrategic_sphere
"""

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

import requests
import yaml

COURTLISTENER_API = "https://www.courtlistener.com/api/rest/v4/opinions"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "CASE_LAW"


def sanitize_filename(case_name: str) -> str:
    name = re.sub(r'[^\w\s-]', '', case_name)
    name = re.sub(r'[-\s]+', '_', name).strip('_')
    return name[:120]


def build_frontmatter(meta: dict) -> str:
    front = {
        "citation": meta.get("citation", ""),
        "case_name": meta.get("case_name", ""),
        "year": meta.get("year", ""),
        "jurisdiction": meta.get("jurisdiction", "Illinois Appellate Court"),
        "core_holding": meta.get("core_holding", ""),
        "strategic_sphere": meta.get("strategic_sphere", ""),
    }
    return yaml.dump(front, default_flow_style=False, allow_unicode=True).strip()


def write_md(output_path: Path, meta: dict, body: str):
    front = build_frontmatter(meta)
    content = f"""---
{front}
---

# {meta['case_name']}
### {meta['citation']} ({meta['year']})

{body}
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')
    return output_path


def search_courtlistener(citation: str) -> dict | None:
    url = f"{COURTLISTENER_API}/?search={requests.utils.quote(citation)}&format=json"
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        for r in results:
            cite_str = r.get("citation", [])
            if isinstance(cite_str, list):
                cite_str = ", ".join(cite_str)
            if citation.lower() in cite_str.lower():
                return r
        return results[0]
    except requests.RequestException:
        return None


def fetch_from_cl(meta: dict) -> str | None:
    citation = meta.get("citation", "")
    result = search_courtlistener(citation)
    if not result:
        return None
    plain_text = result.get("plain_text") or ""
    html_text = result.get("html") or ""
    html_lawbox = result.get("html_lawbox") or ""
    html_columbia = result.get("html_columbia") or ""
    body = plain_text or ""
    if not body:
        import html as html_mod
        for src in [html_text, html_lawbox, html_columbia]:
            if src:
                body = re.sub(r'<[^>]+>', ' ', src)
                body = html_mod.unescape(body)
                body = re.sub(r'\s{3,}', '\n\n', body).strip()
                if body:
                    break
    return body if body else None


def skeleton_body(meta: dict) -> str:
    lines = [
        f"*{meta.get('core_holding', 'No core holding provided.')}*",
        "",
        "## Opinion Text",
        "",
        "> ## Manual Append Required",
        ">",
        "> This opinion could not be automatically retrieved from public endpoints",
        f"> (citation: {meta.get('citation', 'unknown')}).",
        "> Paste the full-text opinion below this block and remove this notice.",
        ">",
    ]
    return "\n".join(lines)


def parse_citation(s: str) -> dict:
    known = {
        "376 Ill. App. 3d 269": {
            "case_name": "In re Marriage of Daines",
            "year": 2007,
            "jurisdiction": "Illinois Appellate Court, Second District",
            "core_holding": "Severe parental alienation impacting the minor child's best interests is actionable emotional abuse and constitutes a material change in circumstances.",
            "strategic_sphere": "Sphere C (Psychological/Alienation)",
        },
        "2023 IL App (1st) 221103-U": {
            "case_name": "In re Marriage of Keigher",
            "year": 2023,
            "jurisdiction": "Illinois Appellate Court, First District",
            "core_holding": "Coercive control dynamics and the risk of overturning parenting time restrictions require careful judicial scrutiny to prevent further harm to the parent-child relationship.",
            "strategic_sphere": "Sphere C (Psychological/Alienation)",
        },
    }
    base = known.get(s, {})
    if not base:
        m = re.match(r'(\d{4})\s', s)
        year = int(m.group(1)) if m else 0
        base = {"case_name": "", "year": year, "jurisdiction": "Illinois Appellate Court",
                "core_holding": "", "strategic_sphere": ""}
    base["citation"] = s
    return base


def process_citation(citation: str, output_dir: Path, no_fetch: bool = False) -> Path | None:
    meta = parse_citation(citation)
    name = sanitize_filename(meta.get("case_name") or meta["citation"])
    out_path = output_dir / f"{name}.md"

    body = None
    if not no_fetch:
        body = fetch_from_cl(meta)

    if body:
        write_md(out_path, meta, body)
        status = f"FETCHED ({len(body)} chars)"
    else:
        body = skeleton_body(meta)
        write_md(out_path, meta, body)
        status = "SKELETON (manual append required)"

    print(f"  [{status}] {out_path.name}")
    return out_path


def process_batch_file(path: str, output_dir: Path, no_fetch: bool = False):
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            citation = parts[0].strip()
            if citation:
                process_citation(citation, output_dir, no_fetch)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Illinois appellate opinions and write .md digital twins to CASE_LAW/")
    parser.add_argument('--cite', type=str, help='Single citation to fetch (e.g. "376 Ill. App. 3d 269")')
    parser.add_argument('--batch-file', type=str, help='Path to batch file (tab-separated, one per line)')
    parser.add_argument('--output-dir', type=str, default=str(DEFAULT_OUTPUT),
                        help=f'Output directory (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--no-fetch', action='store_true',
                        help='Skip API fetch; generate skeleton only')
    args = parser.parse_args()

    if not args.cite and not args.batch_file:
        parser.print_help()
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.batch_file:
        process_batch_file(args.batch_file, output_dir, args.no_fetch)
    if args.cite:
        process_citation(args.cite, output_dir, args.no_fetch)


if __name__ == '__main__':
    main()
