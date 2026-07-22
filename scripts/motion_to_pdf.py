# Copyright (C) 2026 Byers Brands, LLC
# /// script
# dependencies = ["markdown", "weasyprint", "beautifulsoup4"]
# ///

"""
Convert markdown legal motion drafts into DeKalb County court-ready PDFs 
matching Petitioner's exact Sans-Serif 16pt/14pt/13pt/12pt typography hierarchy.

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
    
    # Tag pleading components structurally based on text content
    for p in soup.find_all(["p", "h1", "h2", "h3"]):
        text = p.get_text().strip()
        
        # 1. Top Court Header Line (16pt Bold)
        if "IN THE CIRCUIT COURT" in text.upper():
            p['class'] = p.get('class', []) + ['court-header']
            
        # 2. Case Number Line (13pt Regular, Unbolded)
        elif re.search(r'Case\s+No\.?\s*[\d\w]+', text, re.IGNORECASE):
            p['class'] = p.get('class', []) + ['case-number']
            # Remove inner <strong> tags to unbold the case number line
            for strong in p.find_all("strong"):
                strong.unwrap()
                
        # 3. Motion Title (14pt Bold)
        elif ("EMERGENCY MOTION" in text.upper() or "PETITIONER'S" in text.upper() or "MOTION FOR" in text.upper() or "PETITION FOR" in text.upper()) and "CIRCUIT COURT" not in text.upper():
            p['class'] = p.get('class', []) + ['motion-title']
            
        # 4. Roman Numeral Section Headings (12pt Bold - No Jumbo)
        elif re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s+', text):
            p['class'] = p.get('class', []) + ['section-heading']
            
        # 5. Lettered Subsection Headings (12pt Bold)
        elif re.match(r'^[A-Z]\.\s+', text) and len(text) < 100:
            p['class'] = p.get('class', []) + ['subsection-heading']

    # Insert signature line spacing (2 empty lines above name)
    for p in soup.find_all("p"):
        if "DAVID C. BYERS" in p.get_text() and not p.find("br"):
            p.insert(0, BeautifulSoup("<br/><br/>", "html.parser"))
            
    return str(soup)

def convert_motion_to_pdf(input_file, output_file, margin="0.72"):
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            md_text = f.read()

        # Render Markdown to HTML and apply structural class tagging
        html_raw = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html_tagged = transform_pleading_structure(html_raw)

        custom_css = CSS(string=f"""
            @page {{
                size: letter portrait;
                margin: {margin}in;
                @bottom-right {{
                    content: "Page " counter(page) " of " counter(pages);
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 9pt;
                }}
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

            /* 1. Court Caption Header (16pt Bold) */
            .court-header {{
                font-size: 16pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 0 !important;
                margin-bottom: 2pt !important;
                line-height: 1.2 !important;
            }}

            /* 2. Case Number Line (13pt Regular, Unbolded) */
            .case-number {{
                font-size: 13pt !important;
                font-weight: normal !important;
                text-align: left !important;
                margin-top: 2pt !important;
                margin-bottom: 12pt !important;
            }}

            /* 3. Document / Motion Title (14pt Bold) */
            .motion-title {{
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

            /* Lists & Nested Formatting */
            ul, ol {{
                margin-top: 0;
                margin-bottom: 8pt;
                padding-left: 20pt;
            }}

            li {{
                margin-bottom: 4pt;
                font-size: 12pt;
                word-wrap: break-word;
                hypens: auto;
            }}

            /* Nested list items (for hospital names, etc.) */
            li li {{
                padding-left: 10pt;
                word-wrap: break-word;
                hypens: auto;
            }}

            li li li {{
                padding-left: 10pt;
                word-wrap: break-word;
                hypens: auto;
            }}

            /* Force word wrap for long bold text in lists */
            li strong {{
                word-wrap: break-word !important;
                hypens: auto !important;
                display: inline !important;
                overflow-wrap: break-word !important;
                word-break: break-all !important;
            }}

            /* Ensure nested bold text remains 12pt and wraps properly */
            strong {{
                font-size: 12pt;
                word-wrap: break-word !important;
                overflow-wrap: break-word !important;
            }}

            .court-header strong {{
                font-size: 16pt !important;
            }}

            .motion-title strong {{
                font-size: 14pt !important;
            }}

            /* Verification & Certificate Blocks */
            .verification, .certificate-of-service {{
                page-break-inside: avoid;
                break-inside: avoid;
            }}

            /* Table Formatting for Motion Backlog */
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 12pt;
                font-size: 10pt;
            }}

            th, td {{
                border: 1px solid #dddddd;
                padding: 4pt;
                text-align: left;
                vertical-align: top;
            }}

            th {{
                background-color: #f5f5f5;
                font-weight: bold;
                padding: 6pt 4pt;
            }}

            /* Column width constraints */
            th:nth-child(1), td:nth-child(1) {{ width: 8%; }}      /* # column */
            th:nth-child(2), td:nth-child(2) {{ width: 35%; }}     /* Motion Title column */
            th:nth-child(3), td:nth-child(3) {{ width: 25%; }}     /* Primary Statutes column */
            th:nth-child(4), td:nth-child(4) {{ width: 27%; }}     /* Core Argument column */
            th:nth-child(5), td:nth-child(5) {{ width: 5%; }}      /* Status column */

            /* Enable word wrapping in table cells */
            td {{
                word-wrap: break-word;
                hypens: auto;
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

    args = parser.parse_args()
    output_pdf = args.output or args.input.rsplit(".", 1)[0] + ".pdf"
    convert_motion_to_pdf(args.input, output_pdf, margin=str(args.margin))