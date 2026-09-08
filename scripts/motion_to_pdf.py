# Copyright (C) 2026 Byers Brands, LLC
# /// script
# dependencies = ["markdown", "weasyprint", "beautifulsoup4"]
# ///

"""
Convert markdown legal motion drafts into DeKalb County court-ready PDFs
matching Petitioner's exact Sans-Serif 16pt/14pt/13pt/12pt typography hierarchy.

Typography Hierarchy:
  - Court Header: 16pt Bold
  - Case Number:  13pt Regular (Unbolded)
  - Motion Title: 14pt Bold (ALL CAPS)
  - Body / Headings / Lists: 12pt

Usage:
    uv run dc13_hive/scripts/motion_to_pdf.py <input.md> [output.pdf] [options]
"""

import sys
import re
import argparse
import markdown
from bs4 import BeautifulSoup
from weasyprint import HTML, CSS

def transform_pleading_structure(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    # Strip Change Log sections from court-ready PDF output
    for heading in list(soup.find_all(["h1", "h2", "h3", "h4", "p"])):
        text = heading.get_text().strip()
        if re.search(r'\bchange\s*log\b', text, re.IGNORECASE):
            prev = heading.find_previous_sibling()
            if prev and prev.name == "hr":
                prev.decompose()
            curr = heading
            while curr:
                nxt = curr.find_next_sibling()
                curr.decompose()
                curr = nxt
            break

    # State flag to restrict caption/title tagging strictly to the top header area
    in_header_zone = True

    for p in soup.find_all(["p", "h1", "h2", "h3"]):
        text = p.get_text().strip()
        text_upper = text.upper()

        # Exit header zone immediately upon encountering body preamble or Section I
        if text_upper.startswith("NOW COMES") or re.match(r'^(I|1)\.\s+', text):
            in_header_zone = False

        if in_header_zone:
            # 1. Top Court Header Line (16pt Bold)
            if "IN THE CIRCUIT COURT" in text_upper:
                p['class'] = p.get('class', []) + ['court-header']

            # 2. Case Number Line (13pt Regular, Unbolded)
            elif re.match(r'^\s*(?:Case\s+No\.?|No\.?)\s*[\d\w]+', text, re.IGNORECASE) and len(text) < 80:
                p['class'] = p.get('class', []) + ['case-number']
                # Strip all inner strong and b tags to force regular weight
                for tag in p.find_all(["strong", "b"]):
                    tag.unwrap()

            # 3. Motion Title (14pt Bold) - Only applied inside header zone
            # Use \b word boundaries so "PETITION" doesn't false-match "PETITIONER" in party names
            elif any(re.search(r'\b' + kw + r'\b', text_upper) for kw in ["MOTION", "PETITION", "ORDER", "RESPONSE", "REPLY", "REQUEST", "NOTICE", "MEMORANDUM"]) and "CIRCUIT COURT" not in text_upper:
                p['class'] = p.get('class', []) + ['motion-title']
                in_header_zone = False  # Title found; close header zone
        else:
            # 4. Roman Numeral Section Headings (12pt Bold)
            if re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s+', text):
                p['class'] = p.get('class', []) + ['section-heading']

            # 5. Lettered Subsection Headings (12pt Bold)
            elif re.match(r'^[A-Z]\.\s+', text) and len(text) < 120:
                p['class'] = p.get('class', []) + ['subsection-heading']

            # 6. Closing Line (Respectfully submitted)
            if text_upper.startswith("RESPECTFULLY SUBMITTED"):
                p['class'] = p.get('class', []) + ['closing-line']

            # 7. Verification / Certificate of Service Headings
            if any(k in text_upper for k in ["VERIFICATION", "CERTIFICATE OF SERVICE", "PROOF OF SERVICE"]):
                p['class'] = p.get('class', []) + ['verification-header']

    # Tag hr signature rules (e.g. lines of underscores in markdown)
    for hr in soup.find_all("hr"):
        nxt = hr.find_next_sibling()
        if nxt and nxt.name == "p":
            nxt_t = nxt.get_text().strip()
            if re.search(r"\b(?:David\s+C\.?\s*Byers|Signature|Printed Name|Notary Public)\b", nxt_t, re.IGNORECASE):
                hr['class'] = hr.get('class', []) + ['signature-rule']

    # Group signature blocks outside the header zone
    in_header_zone = True
    for elem in list(soup.find_all(["p", "hr"])):
        if elem.name == "p":
            text = elem.get_text().strip()
            text_upper = text.upper()
            if text_upper.startswith("NOW COMES") or re.match(r'^(I|1)\.\s+', text) or "ADMINISTRATIVE" in text_upper or "GROUP " in text_upper or "PRODUCTION RIDER" in text_upper or "motion-title" in elem.get("class", []):
                in_header_zone = False

            if in_header_zone:
                continue

            # Identify if this is a signature line
            is_sig = False
            if re.match(r'^(?:/s/\s*)?David\s+C\.?\s*Byers\b', text, re.IGNORECASE):
                is_sig = True
            elif text in ["David C. Byers", "David C. Byers, Pro Se", "David C. Byers, Petitioner Pro Se", "David C. Byers, Petitioner", "David C. Byers, Respondent"]:
                is_sig = True
            elif elem.find_previous_sibling() and "signature-rule" in elem.find_previous_sibling().get("class", []):
                is_sig = True

            if is_sig and not (elem.parent and "signature-block" in elem.parent.get("class", [])):
                prev = elem.find_previous_sibling()
                has_rule = prev and prev.name == "hr" and "signature-rule" in prev.get("class", [])

                sig_classes = ["signature-block"]
                if has_rule:
                    sig_classes.append("has-rule")

                sig_block = soup.new_tag("div", attrs={"class": " ".join(sig_classes)})
                if has_rule:
                    prev.insert_before(sig_block)
                    sig_block.append(prev)
                else:
                    elem.insert_before(sig_block)

                sig_block.append(elem)
                elem['class'] = elem.get('class', []) + ['signature-name']

                # Slurp subsequent contact lines
                nxt = sig_block.find_next_sibling()
                while nxt and nxt.name == "p":
                    nxt_t = nxt.get_text().strip()
                    if any(c in nxt_t.lower() for c in ["1st st", "dekalb", "60115", "(815)", "@gmail", "pro se", "petitioner", "printed name", "title"]):
                        following = nxt.find_next_sibling()
                        nxt['class'] = nxt.get('class', []) + ['signature-contact']
                        sig_block.append(nxt)
                        nxt = following
                    else:
                        break

    soup = format_tables_and_breaks(soup)
    return str(soup)


def format_tables_and_breaks(soup):
    """
    Intelligently inject colgroups and wrap opportunities for table cells
    without distorting formal court pleading structure.
    """
    for table in soup.find_all("table"):
        # 1. Insert zero-width break opportunities after underscores and slashes
        for cell in table.find_all(["td", "th"]):
            for string in list(cell.strings):
                if "_" in string or "/" in string:
                    # Add zero-width space after _ or / so WeasyPrint can wrap filenames
                    new_text = re.sub(r"([_/])", lambda m: m.group(1) + "\u200b", str(string))
                    string.replace_with(new_text)

        # 2. Determine column widths based on table headers
        headers = [th.get_text().strip() for th in table.find_all("th")]
        col_count = len(headers)
        if col_count == 0:
            first_row = table.find("tr")
            if first_row:
                col_count = len(first_row.find_all(["td", "th"]))

        colgroup = soup.new_tag("colgroup")

        # Universal Exhibits (3 cols: Letter | Document | Used In)
        if col_count == 3 and headers and "Letter" in headers[0]:
            widths = ["10%", "58%", "32%"]
        # Filing-Specific Exhibits (4 cols: # | NOV_10 Filing | Assigned Letters | Pending Exhibits)
        elif col_count == 4 and headers and "#" in headers[0]:
            widths = ["6%", "34%", "14%", "46%"]
        # Master Exhibit Catalog (5 cols: Letter | Exhibit | Source Path | Used In | Status)
        elif col_count == 5 and headers and ("Letter" in headers[0] or "Exhibit" in headers[1]):
            widths = ["9%", "29%", "30%", "16%", "16%"]
        # Cross-Reference Matrix (6+ cols)
        elif col_count >= 6:
            first_width = 16
            rem_width = (100 - first_width) / (col_count - 1)
            widths = [f"{first_width}%"] + [f"{rem_width:.1f}%"] * (col_count - 1)
        # Change Log (2 cols: Date | Change)
        elif col_count == 2 and headers and "Date" in headers[0]:
            widths = ["20%", "80%"]
        # Generic Fallback
        else:
            if col_count > 0:
                widths = [f"{100 / col_count:.1f}%"] * col_count
            else:
                widths = []

        for w in widths:
            col = soup.new_tag("col", style=f"width: {w};")
            colgroup.append(col)

        table.insert(0, colgroup)

    return soup

def convert_motion_to_pdf(input_file, output_file, margin="0.72", page_numbers=True):
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            md_text = f.read()

        # Render Markdown to HTML and apply structural class tagging
        html_raw = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html_tagged = transform_pleading_structure(html_raw)

        page_footer = """
            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-family: Arial, Helvetica, sans-serif;
                font-size: 9pt;
            }
        """ if page_numbers else ""

        custom_css = CSS(string=f"""
            @page {{
                size: letter portrait;
                margin: {margin}in;
                {page_footer}
            }}

            body {{
                font-family: Arial, Helvetica, sans-serif;
                font-size: 12pt;
                line-height: 1.3;
                color: #000000;
                margin-top: 0;
                padding-top: 0;
            }}

            p {{
                margin-top: 0;
                margin-bottom: 8pt;
                font-size: 12pt;
                text-align: justify;
            }}

            /* 1. Main Court Header (16pt Bold) */
            .court-header, .court-header strong, .court-header b {{
                font-size: 16pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 0 !important;
                margin-bottom: 32pt !important;
                line-height: 1.2 !important;
            }}

            /* 2. Case Number Line (13pt Regular, Strictly Unbolded) */
            .case-number, .case-number * {{
                font-size: 13pt !important;
                font-weight: normal !important;
                text-decoration: none !important;
                text-align: left !important;
                margin-top: 2pt !important;
                margin-bottom: 12pt !important;
            }}

            /* 3. Motion Title (14pt Bold) */
            .motion-title, .motion-title strong, .motion-title b {{
                font-size: 14pt !important;
                font-weight: bold !important;
                text-align: left !important;
                text-transform: uppercase !important;
                margin-top: 12pt !important;
                margin-bottom: 14pt !important;
                line-height: 1.25 !important;
            }}

            /* 4. Section Headings (12pt Bold - Strict Override) */
            .section-heading, h1, h2, h3 {{
                font-size: 12pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 12pt !important;
                margin-bottom: 6pt !important;
                page-break-after: avoid;
                break-after: avoid;
            }}

            /* 5. Subsection Headings (12pt Bold) */
            .subsection-heading {{
                font-size: 12pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 10pt !important;
                margin-bottom: 4pt !important;
                page-break-after: avoid;
                break-after: avoid;
            }}

            /* General Heading Fallbacks (non-motion markdown docs: indexes, ledgers) */
            h1:not(.court-header):not(.motion-title) {{
                font-size: 14pt !important;
                font-weight: bold !important;
                margin-top: 10pt !important;
                margin-bottom: 8pt !important;
                text-transform: uppercase;
            }}

            h2:not(.section-heading) {{
                font-size: 11pt !important;
                font-weight: bold !important;
                margin-top: 10pt !important;
                margin-bottom: 6pt !important;
                border-bottom: 0.5pt solid #ccc;
                padding-bottom: 2pt;
            }}

            h3:not(.subsection-heading) {{
                font-size: 10pt !important;
                font-weight: bold !important;
                margin-top: 8pt !important;
                margin-bottom: 4pt !important;
            }}

            /* Lists & Body Formatting (12pt Default) */
            ul, ol {{
                margin-top: 0;
                margin-bottom: 8pt;
                padding-left: 20pt;
            }}

            li {{
                margin-bottom: 4pt;
                font-size: 12pt;
                overflow-wrap: break-word;
                hyphens: auto;
            }}

            li li, li li li {{
                padding-left: 10pt;
                overflow-wrap: break-word;
                hyphens: auto;
            }}

            strong, li strong {{
                font-size: 12pt;
                overflow-wrap: break-word !important;
                display: inline !important;
            }}

            /* Verification & Certificate Blocks */
            .verification, .certificate-of-service, .verification-header {{
                page-break-after: avoid !important;
                break-after: avoid !important;
            }}

            /* Closing Statement (Respectfully submitted) */
            .closing-line {{
                page-break-after: avoid !important;
                break-after: avoid !important;
                margin-top: 12pt !important;
                margin-bottom: 0 !important;
            }}

            /* Signature Block & Rules */
            .signature-block {{
                page-break-inside: avoid !important;
                break-inside: avoid !important;
                margin-top: 48pt !important; /* ~0.67 inch / 4 blank lines of signature room */
                margin-bottom: 12pt !important;
            }}

            .signature-block.has-rule {{
                margin-top: 0 !important; /* Spacing handled by hr.signature-rule */
            }}

            .signature-block p {{
                margin-top: 0 !important;
                margin-bottom: 2pt !important; /* Tight court contact lines */
                text-align: left !important;
            }}

            hr.signature-rule {{
                border: none !important;
                border-top: 1pt solid #000000 !important;
                width: 250pt !important;
                margin-top: 48pt !important; /* Space above rule for physical signature */
                margin-bottom: 4pt !important;
                margin-left: 0 !important;
                page-break-after: avoid !important;
                break-after: avoid !important;
            }}

            /* High-Density Court Table Styling */
            table {{
                width: 100% !important;
                table-layout: fixed !important; /* Enforces colgroup percentage widths */
                border-collapse: collapse !important;
                margin-top: 6pt !important;
                margin-bottom: 10pt !important;
                font-size: 8.5pt !important;
                line-height: 1.25 !important;
            }}

            thead {{
                display: table-header-group !important;
            }}

            tr {{
                /* Allow rows to split across page boundaries to prevent 3-inch empty holes */
                page-break-inside: auto !important;
                break-inside: auto !important;
            }}

            th {{
                background-color: #f2f2f2 !important;
                font-weight: bold !important;
                text-align: left;
                padding: 3.5pt 4.5pt !important;
                border: 0.5pt solid #777 !important;
                font-size: 8.5pt !important;
                vertical-align: bottom !important;
            }}

            td {{
                padding: 3pt 4.5pt !important;
                border: 0.5pt solid #aaa !important;
                vertical-align: top !important;
                font-size: 8.5pt !important;
                overflow-wrap: break-word !important;
                word-break: normal !important;
            }}

            /* Ensure narrow index columns center text and do not split letter codes */
            table colgroup col:first-child + col + col {{
                /* preserves default flow */
            }}

            /* First column styling for index tables */
            th:first-child, td:first-child {{
                text-align: center;
                white-space: nowrap; /* Prevents PD-28 from breaking onto two lines */
            }}

            /* Checkbox and matrix table alignments */
            td:empty {{
                background-color: #fafafa;
            }}

            /* Ensure inline code in tables matches table typography */
            td code, th code {{
                font-family: inherit !important;
                font-size: 8pt !important;
                background-color: #f8f8f8;
                padding: 1pt 2pt;
                border: 0.5pt solid #e0e0e0;
                overflow-wrap: break-word !important;
                word-break: break-word !important;
            }}
        """)

        HTML(string=html_tagged).write_pdf(output_file, stylesheets=[custom_css])
        print(f"  [SUCCESS] Refactored Motion PDF rendered -> {output_file}")
        return True

    except Exception as e:
        print(f"  [ERROR] Motion PDF conversion failed: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert motion Markdown to Court-Ready Sans-Serif PDF.")
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("output", nargs="?", default=None, help="Output PDF file")
    parser.add_argument("--margin", type=float, default=0.72, help="Page margin in inches (default: 0.72)")
    parser.add_argument("--no-page-numbers", action="store_true", help="Omit the 'Page X of Y' footer")

    args = parser.parse_args()
    output_pdf = args.output or args.input.rsplit(".", 1)[0] + ".pdf"
    convert_motion_to_pdf(args.input, output_pdf, margin=str(args.margin), page_numbers=not args.no_page_numbers)
