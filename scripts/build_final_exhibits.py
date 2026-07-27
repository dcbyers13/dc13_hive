#!/usr/bin/env python3
"""
build_final_exhibits.py — Generate cover sheets, convert to PDF, and merge
with underlying exhibit files into unified EXHIBIT_[LETTER].pdf outputs.

Usage:
    uv run dc13_hive/scripts/build_final_exhibits.py [--dry-run] [--motion N]

Outputs go to: PRINT/02_EXHIBITS/MOTION_[X]/EXHIBIT_[LETTER].pdf
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from pypdf import PdfReader, PdfWriter

# ── Configuration ──────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent.parent / "25FA152"
PRINT_DIR = BASE / "PRINT" / "02_EXHIBITS"
DRAFTS_DIR = BASE / "LEGAL_FILE" / "01_DRAFTS"
SCRIPTS_DIR = Path(__file__).resolve().parent
MOTION_TO_PDF = SCRIPTS_DIR / "motion_to_pdf.py"

# DeKalb County caption for cover sheets
CAPTION_HEADER = "IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL CIRCUIT DEKALB COUNTY, ILLINOIS"
CAPTION_CASE = "Case No. 25FA152"
CAPTION_PARTIES = "DAVID C. BYERS, Petitioner, vs. PAULETTA D. DONATELLO, Respondent."

# Motion metadata
MOTIONS = {
    1: {"file": "EMERGENCY_MOTION_RETURN_TO_JURISDICTION.md", "title": "EMERGENCY MOTION RETURN TO JURISDICTION"},
    2: {"file": "OMNIBUS_MOTION_TO_COMPEL_RECORDS.md", "title": "OMNIBUS MOTION TO COMPEL RECORDS"},
    3: {"file": "MOTION_ADDRESS_ALIENATION_AND_ENDANGERMENT.md", "title": "MOTION ADDRESSING PARENTAL ALIENATION AND CHILD ENDANGERMENT"},
    4: {"file": "SUPPLEMENTAL_PETITION_RULE_TO_SHOW_CAUSE.md", "title": "SUPPLEMENTAL PETITION RULE TO SHOW CAUSE"},
    5: {"file": "MOTION_TO_COMPEL_GAL_REPORT.md", "title": "EMERGENCY MOTION TO COMPEL GAL REPORT"},
    6: {"file": "PETITION_TO_MODIFY.md", "title": "PETITION TO MODIFY ALLOCATION JUDGMENT"},
}


def discover_exhibits():
    """Scan PRINT/02_EXHIBITS/ and return {motion_num: {letter: folder_path}}."""
    exhibits = {}
    for motion_dir in sorted(PRINT_DIR.iterdir()):
        if not motion_dir.is_dir() or not motion_dir.name.startswith("MOTION_"):
            continue
        try:
            motion_num = int(motion_dir.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        exhibits[motion_num] = {}
        for letter_dir in sorted(motion_dir.iterdir()):
            if not letter_dir.is_dir():
                continue
            letter = letter_dir.name.upper()
            if len(letter) == 1 and letter.isalpha():
                pdfs = sorted(letter_dir.glob("*.pdf"))
                if pdfs:
                    exhibits[motion_num][letter] = {"folder": letter_dir, "pdfs": pdfs}
    return exhibits


def generate_cover_sheet_md(letter, motion_num, exhibit_count):
    """Generate a Markdown cover sheet for a single exhibit."""
    motion_info = MOTIONS.get(motion_num, {"title": "EXHIBIT"})
    title = f"EXHIBIT {letter}"

    md = f"""**{CAPTION_HEADER}**

**{CAPTION_CASE}**

**{CAPTION_PARTIES}**

---

# {title}

**{motion_info['title']}**

---

**Exhibit {letter}** — {exhibit_count} document{'s' if exhibit_count > 1 else ''} enclosed.

**Prepared for:** August 4, 2026 Hearing, 9:00 AM, DeKalb County Room 330

---

*This exhibit is submitted in support of Petitioner's {motion_info['title']} filed in the above-captioned matter.*
"""
    return md


def md_to_pdf(md_text, output_pdf):
    """Convert Markdown text to PDF using weasyprint (same engine as motion_to_pdf.py)."""
    try:
        import markdown as md_lib
    except ImportError:
        # Fallback: use subprocess to call motion_to_pdf.py
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md_text)
            tmp_md = f.name
        try:
            subprocess.run(
                [sys.executable, str(MOTION_TO_PDF), tmp_md, str(output_pdf)],
                check=True, capture_output=True, timeout=30
            )
        finally:
            os.unlink(tmp_md)
        return
    from weasyprint import HTML

    html_body = md_lib.markdown(md_text, extensions=["tables", "smarty"])
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@page {{ size: letter; margin: 1in 1in 1in 1in; }}
body {{ font-family: "Times New Roman", Times, serif; font-size: 12pt; line-height: 1.5; color: #000; }}
h1 {{ font-size: 14pt; text-align: center; text-transform: uppercase; margin-top: 2em; }}
p {{ margin: 0.5em 0; }}
strong {{ font-weight: bold; }}
hr {{ border: none; border-top: 1px solid #000; margin: 1em 0; }}
</style>
</head><body>{html_body}</body></html>"""
    HTML(string=full_html).write_pdf(str(output_pdf))


def merge_pdfs(cover_pdf, content_pdfs, output_pdf):
    """Merge cover sheet PDF + content PDFs into a single file."""
    writer = PdfWriter()

    # Add cover sheet if available
    if cover_pdf and Path(cover_pdf).exists():
        reader = PdfReader(str(cover_pdf))
        for page in reader.pages:
            writer.add_page(page)

    # Add content PDFs in order
    for pdf_path in content_pdfs:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            writer.add_page(page)

    with open(output_pdf, "wb") as f:
        writer.write(f)

    return len(writer.pages)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build final exhibit PDFs with cover sheets")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--motion", type=int, help="Process only this motion number (1-6)")
    args = parser.parse_args()

    exhibits = discover_exhibits()
    results = []

    for motion_num in sorted(exhibits.keys()):
        if args.motion and motion_num != args.motion:
            continue

        motion_dir = PRINT_DIR / f"MOTION_{motion_num}"
        print(f"\n{'='*60}")
        print(f"MOTION #{motion_num}: {MOTIONS.get(motion_num, {}).get('title', 'UNKNOWN')}")
        print(f"{'='*60}")

        for letter in sorted(exhibits[motion_num].keys()):
            info = exhibits[motion_num][letter]
            folder = info["folder"]
            pdfs = info["pdfs"]
            count = len(pdfs)

            # Generate cover sheet
            md_text = generate_cover_sheet_md(letter, motion_num, count)

            if args.dry_run:
                print(f"  [{letter}] {count} file(s) — cover sheet + merge → EXHIBIT_{letter}.pdf")
                for p in pdfs:
                    print(f"         {p.name}")
                continue

            # Write cover sheet MD
            cover_md_path = folder / f"COVER_EXHIBIT_{letter}.md"
            cover_md_path.write_text(md_text, encoding="utf-8")

            # Convert cover sheet to PDF
            cover_pdf_path = folder / f"COVER_EXHIBIT_{letter}.pdf"
            try:
                md_to_pdf(md_text, cover_pdf_path)
            except Exception as e:
                print(f"  [{letter}] ⚠️  Cover sheet PDF failed: {e}")
                # Fall back to just merging without cover
                cover_pdf_path = None

            # Merge
            output_pdf = folder / f"EXHIBIT_{letter}.pdf"
            pages = merge_pdfs(cover_pdf_path if cover_pdf_path and cover_pdf_path.exists() else None, pdfs, output_pdf)
            size_kb = output_pdf.stat().st_size / 1024

            print(f"  [{letter}] ✅ {pages} pages, {size_kb:.0f} KB → {output_pdf.name}")
            results.append({
                "motion": motion_num,
                "letter": letter,
                "pages": pages,
                "size_kb": round(size_kb),
                "files": count,
                "status": "OK"
            })

    if not args.dry_run and results:
        print(f"\n{'='*60}")
        print(f"SUMMARY: {len(results)} exhibits generated")
        print(f"{'='*60}")
        print(f"{'Motion':<10} {'Letter':<10} {'Files':<8} {'Pages':<8} {'Size':<10}")
        print(f"{'-'*46}")
        for r in results:
            print(f"#{r['motion']:<9} {r['letter']:<10} {r['files']:<8} {r['pages']:<8} {r['size_kb']} KB")


if __name__ == "__main__":
    main()
