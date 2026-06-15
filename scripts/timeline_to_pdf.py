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
# dependencies = ["markdown", "weasyprint", "beautifulsoup4"]
# ///

"""
Convert markdown legal documents to print-ready PDFs.

Usage:
    uv run dc13_hive/scripts/timeline_to_pdf.py <input.md> [output.pdf] [options]

Options:
    --orientation {landscape,portrait}   Page orientation (default: landscape)
    --margin <in>                        Page margin (default: 0.70)
    --font-size <pt>                     Base body font size (default: 12)
    --first-paragraph-size <pt>          Font size for first paragraph/subheading (default: 13)
    --case-name <text>                   Case name for header
    --case-number <text>                 Case number for header
    --prepared-by <text>                 Prepared-by line for header
    --no-header                          Omit page header text (case name, prepared-by)
    --no-footer                          Omit page number footer
    --no-citation-manifest               Skip citation manifest generation
    --table-of-contents                  Prepend a table of contents page
    --non-standard                       Uniform table font, equal-width columns, handles up to 6 cols

Examples:
    uv run timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md
    uv run timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md --margin 0.5 --font-size 11
    uv run timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md --orientation portrait
    uv run timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md --table-of-contents
    uv run timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md --table-of-contents --non-standard
"""

import sys
import json
import re
import argparse
import markdown
from weasyprint import HTML, CSS


CASE_NAME = "BYERS v. DONATELLO"
CASE_NUMBER = "Case No: 25FA152"
PREPARED_BY = "Prepared by: David Byers"
ORIENTATION = "landscape"
MARGIN = "0.70"
FONT_SIZE = 12
FIRST_P_SIZE = 13


def _build_toc_html(html_content, toc_title="TABLE OF CONTENTS"):
    """Parse headings from HTML and return a TOC page as HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")

    headings = []
    for el in soup.find_all(["h1", "h2", "h3"]):
        text = el.get_text().strip()
        level = int(el.name[1])
        headings.append((level, text))

    if not headings:
        return ""

    indent_map = {1: 0, 2: 20, 3: 40}
    toc_lines = []
    toc_lines.append("<div style='font-size: 13pt; font-weight: bold; border-bottom: 1px solid #ccc; margin-bottom: 10px;'>TABLE OF CONTENTS</div>")
    toc_lines.append("<ul style='list-style: none; padding: 0;'>")

    for level, text in headings:
        indent = indent_map.get(level, 0)
        style = f"margin-left: {indent}px;"
        if level == 1:
            style += " font-weight: bold; margin-top: 6px;"
        toc_lines.append(f"  <li style='{style}'>{text}</li>")

    toc_lines.append("</ul>")
    return "\n".join(toc_lines)


def convert_md_to_pdf(
    input_file,
    output_file,
    orientation=ORIENTATION,
    margin=MARGIN,
    font_size=FONT_SIZE,
    first_paragraph_size=FIRST_P_SIZE,
    case_name=CASE_NAME,
    case_number=CASE_NUMBER,
    prepared_by=PREPARED_BY,
    no_header=False,
    no_footer=False,
    no_citation_manifest=False,
    table_of_contents=False,
    non_standard=False,
):
    citation_manifest = {}
    current_section = None
    row_index = 0

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            md_text = f.read()


        html_content = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

        if table_of_contents:
            toc_html = _build_toc_html(html_content)
            if toc_html:
                html_content = toc_html + "\n<hr style='page-break-after: always;'>\n" + html_content

        if not no_citation_manifest:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_content, "html.parser")

            for element in soup.find_all():
                if element.name in ["h1", "h2", "h3"]:
                    current_section = element.get_text().strip()
                    row_index = 0
                elif element.name == "tr":
                    cells = element.find_all(["td", "th"])
                    if len(cells) >= 2:
                        event_text = cells[1].get_text().strip() if len(cells) > 1 else ""
                        event_key = f"{current_section}:{event_text}"
                        citation_manifest[event_key] = {
                            "section": current_section,
                            "row_index": row_index,
                            "page_number": None,
                        }
                        row_index += 1

        top_left = f'content: "{case_name}\\A {case_number}";' if not no_header else "content: '';"
        top_right = f'content: "{prepared_by}";' if not no_header else "content: '';"
        bottom_right = 'content: "Page " counter(page) " of " counter(pages)";' if not no_footer else "content: '';"

        table_css = f"""
            table {{
                width: 100%;
                border-collapse: collapse;
                table-layout: fixed;
            }}

            tr {{ break-inside: avoid; page-break-inside: avoid; }}

            th, td {{
                border: 1pt solid black;
                padding: 6px;
                vertical-align: top;
                word-break: break-all;
            }}
            th {{ background-color: #f0f0f0; font-weight: bold; }}

            /* Standard column widths */
            th:nth-child(1), td:nth-child(1) {{ width: 10%; }}
            th:nth-child(2), td:nth-child(2) {{ width: 25%; }}
            th:nth-child(3), td:nth-child(3) {{ width: 10%; }}
            th:nth-child(4), td:nth-child(4) {{ width: 25%; }}

            th:nth-child(5), td:nth-child(5) {{ width: 25%; }}
            th:nth-child(6), td:nth-child(6) {{ width: 5%; }}
        """

        if non_standard:
            table_css = f"""
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    table-layout: fixed;
                }}

                tr {{ break-inside: avoid; page-break-inside: avoid; }}

                th, td {{
                    border: 1pt solid black;
                    padding: 4px;
                    vertical-align: top;
                    overflow-wrap: break-word;
                    word-wrap: break-word;
                    font-size: {font_size}pt;
                    font-family: serif;
                }}
                th {{ background-color: #f0f0f0; font-weight: bold; }}
            """

        custom_css = CSS(string=f"""
            @page {{
                size: letter {orientation};
                margin: {margin}in;

                @top-left {{
                    {top_left}
                    font-family: serif;
                    font-size: 10pt;
                    white-space: pre;
                    font-weight: bold;
                }}

                @top-right {{
                    {top_right}
                    font-family: serif;
                    font-size: 10pt;
                }}

                @bottom-right {{
                    {bottom_right}
                    font-family: serif;
                    font-size: 9pt;
                }}
            }}

            body {{ font-family: serif; font-size: {font_size}pt; margin-top: 10px; }}

            h1, h2, h3 {{ break-after: avoid; page-break-after: avoid; border-bottom: 1px solid #ccc; }}

            h1:first-child, h2:first-child, h3:first-child {{
                font-size: {first_paragraph_size}pt;
            }}

            p:first-of-type {{
                font-size: {first_paragraph_size}pt;
            }}

            {table_css}

            /* Code blocks */
            pre {{
                font-family: "Courier New", Courier, monospace;
                font-size: {font_size}pt;
                line-height: 1.4;
                white-space: pre;
                overflow: visible;
                background: #f8f8f8;
                border: 1pt solid #ddd;
                padding: 8px;
            }}
            code {{
                font-family: "Courier New", Courier, monospace;
                font-size: {font_size}pt;
            }}

            /* TOC styling */
            ul {{ line-height: 1.6; }}
            li {{ font-family: serif; font-size: {font_size}pt; }}
        """)

        HTML(string=html_content).write_pdf(output_file, stylesheets=[custom_css])

        if not no_citation_manifest:
            manifest_file = output_file.replace(".pdf", "_citation_manifest.json")
            with open(manifest_file, "w") as f:
                json.dump(citation_manifest, f, indent=2)
            print(f"  citation manifest -> {manifest_file}")

        print(f"  pdf -> {output_file}")
        return True

    except Exception as e:
        print(f"  error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert markdown legal documents to print-ready PDFs."
    )
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("output", nargs="?", default=None, help="Output PDF file (default: input name with .pdf)")
    parser.add_argument("--orientation", choices=["landscape", "portrait"], default=ORIENTATION)
    parser.add_argument("--margin", type=float, default=float(MARGIN), help=f"Page margin in inches (default: {MARGIN})")
    parser.add_argument("--font-size", type=int, default=FONT_SIZE, help=f"Base body font size in pt (default: {FONT_SIZE})")
    parser.add_argument("--first-paragraph-size", type=int, default=FIRST_P_SIZE, help=f"First paragraph/subheading size in pt (default: {FIRST_P_SIZE})")
    parser.add_argument("--case-name", default=CASE_NAME)
    parser.add_argument("--case-number", default=CASE_NUMBER)
    parser.add_argument("--prepared-by", default=PREPARED_BY)
    parser.add_argument("--no-header", action="store_true", help="Omit case name/prepared-by from page header")
    parser.add_argument("--no-footer", action="store_true")
    parser.add_argument("--no-citation-manifest", action="store_true")
    parser.add_argument("--table-of-contents", action="store_true", help="Prepend a table of contents page")
    parser.add_argument("--non-standard", action="store_true", help="Uniform table font, equal-width columns, handles up to 6 cols")

    args = parser.parse_args()

    output = args.output or args.input.rsplit(".", 1)[0] + ".pdf"

    convert_md_to_pdf(
        input_file=args.input,
        output_file=output,
        orientation=args.orientation,
        margin=str(args.margin),
        font_size=args.font_size,
        first_paragraph_size=args.first_paragraph_size,
        case_name=args.case_name,
        case_number=args.case_number,
        prepared_by=args.prepared_by,
        no_header=args.no_header,
        no_footer=args.no_footer,
        no_citation_manifest=args.no_citation_manifest,
        table_of_contents=args.table_of_contents,
        non_standard=args.non_standard,
    )
