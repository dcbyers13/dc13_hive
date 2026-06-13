"""
Build a combined PDF binder with outline bookmarks from a directory of PDFs.

Usage:
    python3 dc13_hive/scripts/build_binder_pdf.py <input_dir> [output_name]

Examples:
    python3 dc13_hive/scripts/build_binder_pdf.py BINDER
    python3 dc13_hive/scripts/build_binder_pdf.py BINDER COMBINED_BINDER.pdf
"""

# /// script
# dependencies = ["pypdf"]
# ///

import glob
import os
import sys
from pypdf import PdfWriter


def build_binder(input_dir, output_name="COMBINED_BINDER.pdf"):
    files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    writer = PdfWriter()
    for f in files:
        if os.path.basename(f) == output_name:
            continue
        title = os.path.splitext(os.path.basename(f))[0].replace("_", " ")
        print(f"  {os.path.basename(f)} -> \"{title}\"")
        writer.append(f, outline_item=title)
    output_path = os.path.join(input_dir, output_name)
    writer.write(output_path)
    writer.close()
    print(f"\nDone: {output_path} ({len(files)} files)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    input_dir = sys.argv[1]
    output_name = sys.argv[2] if len(sys.argv) > 2 else "COMBINED_BINDER.pdf"
    build_binder(input_dir, output_name)
