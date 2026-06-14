"""
Build a combined PDF binder from a directory of PDFs.

Usage:
    uv run dc13_hive/scripts/build_binder_pdf.py <input_dir> [output_name] [options]

Options:
    -p, --page-numbers     Add centered page numbers at bottom of each page
    -i, --index            Append alphabetical subject index (uses fpdf2)
    --index-config <json>  JSON file with manual index entries for cross-references
    -o, --output <name>    Output filename (default: COMBINED_BINDER.pdf)

Examples:
    uv run dc13_hive/scripts/build_binder_pdf.py BINDER
    uv run dc13_hive/scripts/build_binder_pdf.py BINDER -p
    uv run dc13_hive/scripts/build_binder_pdf.py BINDER -p -i --index-config index_config.json
"""

# /// script
# dependencies = ["pypdf", "fpdf2"]
# ///

import glob
import json
import os
import sys
import tempfile
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText

PAGE_NUMBER_Y = 30
PAGE_NUMBER_HEIGHT = 20
PAGE_NUMBER_WIDTH = 90
PAGE_NUMBER_RIGHT_PAD = 30  # distance from visual right edge


def _doc_title_from_filename(basename):
    name = os.path.splitext(basename)[0]
    if "_" in name and name.split("_")[0].isdigit():
        name = name.split("_", 1)[1]
    return name.replace("_", " ")


def _add_page_numbers_to_file(filepath):
    """Add centered page number annotations to every page of an existing PDF."""
    reader = PdfReader(filepath)
    writer = PdfWriter()

    # Use append to preserve outlines/bookmarks
    writer.append(reader)

    for i in range(len(reader.pages)):
        page = writer.pages[i]
        mb = page.mediabox
        rot = page.get("/Rotate", 0)
        w = float(mb.width)
        h = float(mb.height)

        # Visual coordinate system dimensions
        if rot in (90, 270):
            vw, vh = h, w
        else:
            vw, vh = w, h

        # Visual position: right side, vertically centered
        vis_left = vw - PAGE_NUMBER_RIGHT_PAD - PAGE_NUMBER_WIDTH
        vis_right = vw - PAGE_NUMBER_RIGHT_PAD
        vis_center_y = vh / 2
        vis_bottom = vis_center_y - PAGE_NUMBER_HEIGHT / 2
        vis_top = vis_center_y + PAGE_NUMBER_HEIGHT / 2

        # Map from visual to unrotated PDF coordinates
        if rot == 90:
            x1 = h - vis_top
            y1 = vis_left
            x2 = h - vis_bottom
            y2 = vis_right
        elif rot == 270:
            x1 = vis_bottom
            y1 = h - vis_right
            x2 = vis_top
            y2 = h - vis_left
        else:
            x1 = vis_left
            y1 = vis_bottom
            x2 = vis_right
            y2 = vis_top

        num = i + 1
        text = f"- {num} -"

        ft = FreeText(
            text=text,
            rect=(x1, y1, x2, y2),
            font="Times-Roman",
            font_size=9,
            border_color=None,
            background_color=None,
        )
        writer.add_annotation(page_number=i, annotation=ft)

    writer.write(filepath)
    writer.close()


def _build_index(files, output_dir, index_config_path, doc_ranges):
    """Build index pages using fpdf2 and return the path, or None if skipped."""
    try:
        from fpdf import FPDF
    except ImportError:
        print("  warning: fpdf2 not installed, skipping index")
        return None

    # Collect entries: auto from doc titles + manual from config
    entries = {}
    for title, (start, end) in sorted(doc_ranges.items(), key=lambda x: x[0].lower()):
        page_str = str(start) if start == end else f"{start}-{end}"
        entries[title] = page_str

    if index_config_path and os.path.exists(index_config_path):
        with open(index_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        for entry in config.get("entries", []):
            subject = entry["subject"]
            if subject in entries:
                entries[subject] += f", {entry['pages']}"
            else:
                entries[subject] = entry["pages"]

    if not entries:
        return None

    sorted_keys = sorted(entries.keys(), key=lambda k: k.lower())

    def _sanitize(text):
        return text.replace("\u2013", "-").replace("\u2014", "--") \
                   .replace("\u2018", "'").replace("\u2019", "'") \
                   .replace("\u201c", '"').replace("\u201d", '"') \
                   .replace("\u2026", "...")

    pdf = FPDF(orientation="L", format="letter")
    use_unicode = False
    for ttf_path in [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Times.ttc",
    ]:
        if os.path.exists(ttf_path):
            try:
                pdf.add_font("TimesUni", "", ttf_path)
                pdf.add_font("TimesUni", "B", ttf_path)
                use_unicode = True
            except Exception:
                pass
            break
    font_family = "TimesUni" if use_unicode else "Times"

    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=36)
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    # Title
    pdf.set_font(font_family, "B", 18)
    pdf.cell(page_width, 12, "INDEX", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # Group by first letter
    current_letter = None
    for key in sorted_keys:
        first = key[0].upper()
        if first != current_letter:
            current_letter = first
            pdf.set_font(font_family, "B", 13)
            pdf.cell(page_width, 8, f"  {current_letter}", new_x="LMARGIN", new_y="NEXT")

        indent = 12
        label = f"     {_sanitize(key)}"
        pages = _sanitize(entries[key])
        pdf.set_font(font_family, size=11)
        label_w = pdf.get_string_width(label)
        pages_w = pdf.get_string_width(pages) + 4
        avail = page_width - indent

        pdf.cell(indent, 6, "")
        pdf.cell(avail - pages_w, 6, label, align="L")
        pdf.cell(pages_w, 6, pages, align="R", new_x="LMARGIN", new_y="NEXT")

    index_path = os.path.join(output_dir, "__index.pdf")
    pdf.output(index_path)
    print(f"  index -> {index_path} ({len(sorted_keys)} entries)")
    return index_path


def build_binder(
    input_dir,
    output_name="COMBINED_BINDER.pdf",
    page_numbers=False,
    index=False,
    index_config=None,
):
    files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    output_path = os.path.join(input_dir, output_name)

    # Phase 1: build combined content
    writer = PdfWriter()
    doc_ranges = {}
    current_page = 1

    for f in files:
        basename = os.path.basename(f)
        if basename == output_name or basename == "__index.pdf":
            continue
        title = _doc_title_from_filename(basename)
        reader = PdfReader(f)
        num_pages = len(reader.pages)
        doc_ranges[title] = (current_page, current_page + num_pages - 1)
        print(f"  {basename} -> \"{title}\" ({num_pages}p)")
        writer.append(f, outline_item=title)
        current_page += num_pages

    # Write combined PDF (no page numbers yet)
    combined = output_path
    writer.write(combined)
    writer.close()

    # Phase 2: (skipped — page numbers deferred to Phase 4)

    # Phase 3: append index at end
    if index:
        index_path = _build_index(files, input_dir, index_config, doc_ranges)
        if index_path:
            print("  appending index...")
            final_writer = PdfWriter()
            final_writer.append(combined)
            final_writer.append(index_path)
            final_writer.write(combined)
            final_writer.close()
            os.remove(index_path)

    # Phase 4: page numbers on final combined (must be last so index gets numbers too)
    if page_numbers:
        print("  adding page numbers...")
        _add_page_numbers_to_file(combined)

    print(f"\nDone: {combined}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_dir = sys.argv[1]
    output_name = "COMBINED_BINDER.pdf"
    page_numbers = False
    index = False
    index_config = None

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ("-p", "--page-numbers"):
            page_numbers = True
        elif arg in ("-i", "--index"):
            index = True
        elif arg == "--index-config":
            i += 1
            if i < len(sys.argv):
                index_config = sys.argv[i]
        elif arg in ("-o", "--output"):
            i += 1
            if i < len(sys.argv):
                output_name = sys.argv[i]
        else:
            output_name = arg
        i += 1

    build_binder(input_dir, output_name, page_numbers, index, index_config)
