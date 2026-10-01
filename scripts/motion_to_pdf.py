# Copyright (C) 2026 Byers Brands, LLC
# /// script
# dependencies = ["markdown", "weasyprint", "beautifulsoup4", "pymupdf"]
# ///

"""
Convert markdown legal motion drafts into DeKalb County court-ready PDFs
matching Petitioner's exact Sans-Serif 16pt/14pt/13pt/12pt typography hierarchy.

Typography Hierarchy:
  - Court Header: 16pt Bold
  - Case Number:  13pt Regular (Unbolded)
  - Motion Title: 14pt Bold (ALL CAPS)
  - Body / Headings / Lists: 12pt

Print-Safe Output (DirectPDF / commercial printer compliant):
  - Every rendered PDF embeds a TrueType sans-serif family (Arial precedence,
    Liberation Sans / DejaVu Sans on Linux) via @font-face so no core/default
    PDF font references or third-party substitution tables are emitted.
  - Extended-Unicode editorial glyphs that the embedded family cannot cover
    (e.g., &#9989;/&#10004; status marks, &#9888; warnings, &#9650; pointers)
    are normalized to clean ASCII labels before rendering.
  - An optional Ghostscript prepress pass (-dEmbedAllFonts=true -dSubsetFonts=true)
    runs automatically when `gs` is on the host, then every font in the output
    is audited for the `embedded` property (via pymupdf).

Usage:
    uv run dc13_hive/scripts/motion_to_pdf.py <input.md> [output.pdf] [options]
"""

import os
import re
import sys
import glob
import shutil
import argparse
import subprocess
import unicodedata
import markdown
from bs4 import BeautifulSoup
from weasyprint import HTML, CSS

# ---------------------------------------------------------------------------
# TrueType font provisioning (100% embedding) & Unicode sanitization
# ---------------------------------------------------------------------------

BUNDLE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts")
)

_FONT_FAMILIES = {
    # Preference order enforced in main() (Arial -> Liberation -> DejaVu).
    "Arial": {
        "regular": "Arial.ttf",
        "bold": "Arial Bold.ttf",
        "italic": "Arial Italic.ttf",
        "bolditalic": "Arial Bold Italic.ttf",
    },
    "Liberation Sans": {
        "regular": "LiberationSans-Regular.ttf",
        "bold": "LiberationSans-Bold.ttf",
        "italic": "LiberationSans-Italic.ttf",
        "bolditalic": "LiberationSans-BoldItalic.ttf",
    },
    "DejaVu Sans": {
        "regular": "DejaVuSans.ttf",
        "bold": "DejaVuSans-Bold.ttf",
        "italic": "DejaVuSans-Oblique.ttf",
        "bolditalic": "DejaVuSans-BoldOblique.ttf",
    },
}

# Glyphs the embedded sans-serif family does NOT map (verified 2026-09-29 against
# Arial/Liberation Sans/DejaVu Sans cmaps). Replaced with print-safe ASCII labels.
_UNICODE_SANITIZE = {
    "\u2705": "[OK]",       # WHITE HEAVY CHECK MARK -> status flag marker
    "\u26A0": "[!]",        # WARNING SIGN -> caution flag marker
    "\u25B2": "[NOTE]",     # BLACK UP-POINTING TRIANGLE -> note marker
    "\u25B3": "[NOTE]",     # WHITE UP-POINTING TRIANGLE -> note marker
}


def _font_search_dirs():
    """Candidate directories searched for an editable TrueType face."""
    dirs = [BUNDLE_DIR]
    if sys.platform == "darwin":
        dirs += ["/System/Library/Fonts/Supplemental", "/Library/Fonts"]
    elif sys.platform in ("win32", "cygwin"):
        windir = os.environ.get("WINDIR", "C:/Windows")
        dirs += [os.path.join(windir, "Fonts")]
    else:
        dirs += [
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype/liberation2",
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/dejavu-sans",
            "/usr/share/fonts/truetype",
        ]
    return dirs


def _resolve_font_family(family="Arial"):
    """Locate regular/bold/italic/bold-italic TrueType faces for `family`.

    Returns (family_name, {style: absolute_path}) or (None, None) when no face
    could be found (caller then falls back to the host font configuration).
    Faces are mirrored into dc13_hive/assets/fonts/ for self-containment.
    """
    family = family if family in _FONT_FAMILIES else "Arial"
    faces = {}
    for style, fname in _FONT_FAMILIES[family].items():
        found = None
        for d in _font_search_dirs():
            candidate = os.path.join(d, fname)
            if os.path.isfile(candidate):
                found = candidate
                break
        faces[style] = found

    if not faces.get("regular"):
        print(
            f"  [WARN] No TrueType '{family}' face found; "
            "falling back to host font configuration (fonts may not embed cleanly)"
        )
        return None, None

    # Mirror the resolved faces into the repo bundle so future runs are
    # reproducible without depending on per-host font installations.
    try:
        os.makedirs(BUNDLE_DIR, exist_ok=True)
        for style, src in list(faces.items()):
            if not src:
                continue
            if os.path.dirname(os.path.abspath(src)) == os.path.abspath(BUNDLE_DIR):
                continue
            dst = os.path.join(BUNDLE_DIR, os.path.basename(src))
            if not os.path.isfile(dst):
                # copy() (not copy2()) — macOS refuses copying system-font
                # xattrs/flags, raising EPERM on copy2's metadata pass.
                shutil.copy(src, dst)
            faces[style] = dst
    except OSError as exc:
        print(f"  [WARN] Could not bundle fonts into {BUNDLE_DIR}: {exc}")

    return family, faces


def _font_face_css(family, faces):
    """Emit @font-face rules forcing WeasyPrint to embed the resolved TTFs."""
    specs = [
        ("regular", "normal", "normal"),
        ("bold", "bold", "normal"),
        ("italic", "normal", "italic"),
        ("bolditalic", "bold", "italic"),
    ]
    rules = []
    for style, weight, fstyle in specs:
        src = faces.get(style)
        if not src:
            continue
        url = "file://" + src.replace("\\", "/").replace(" ", "%20")
        rules.append(
            '@font-face {{ font-family: "{fam}"; font-weight: {w}; '
            'font-style: {fs}; src: url("{url}") format("truetype"); }}'.format(
                fam=family, w=weight, fs=fstyle, url=url
            )
        )
    return "\n".join(rules)


def _sanitize_unicode(text):
    """Replace glyphs the embedded font cannot map with clean ASCII labels.

    Smart quotes, em/en dashes, section signs, bullet points, and ellipses are
    preserved: Arial / Liberation Sans / DejaVu Sans all map them, and legal
    prose should keep typographic fidelity. Normalizes to NFC defensively.
    """
    for char, replacement in _UNICODE_SANITIZE.items():
        text = text.replace(char, replacement)
    return unicodedata.normalize("NFC", text)


def _find_ghostscript():
    gs = shutil.which("gs")
    if gs:
        return gs
    for candidate in ("/opt/local/bin/gs", "/usr/local/bin/gs", "/usr/bin/gs",
                      "/usr/bin/gswin64c", "C:/Program Files/gs/gs*/bin/gswin64c.exe"):
        if glob.glob(candidate):
            return glob.glob(candidate)[0]
    return None


def _ghostscript_sanitize_pdf(pdf_path):
    """Prepress pass: -dEmbedAllFonts=true -dSubsetFonts=true (DirectPDF-safe)."""
    gs = _find_ghostscript()
    if not gs:
        print("  [GS ] Ghostscript not found; skipping prepress sanitization pass")
        return
    tmp = pdf_path + ".gs_tmp.pdf"
    cmd = [gs, "-dNOPAUSE", "-dBATCH", "-q",
           "-sDEVICE=pdfwrite",
           "-dPDFSETTINGS=/prepress",
           "-dEmbedAllFonts=true",
           "-dSubsetFonts=true",
           "-dCompatibilityLevel=1.5",
           f"-sOutputFile={tmp}",
           pdf_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("  [GS ] Ghostscript pass timed out; keeping WeasyPrint output")
        return
    if result.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, pdf_path)
        print("  [GS ] Prepress sanitization applied (EmbedAllFonts + SubsetFonts)")
    else:
        print(f"  [GS ] Ghostscript pass failed: {result.stderr[-300:] if result.stderr else 'unknown error'}")
        if os.path.isfile(tmp):
            os.remove(tmp)


def _audit_fonts(pdf_path):
    """Report per-font embedding status. Uses pymupdf when available,
    else falls back to a raw byte heuristics scan."""
    try:
        import pymupdf
        popen = pymupdf.open
    except ImportError:
        try:
            from fitz import open as popen
        except ImportError:
            popen = None

    if popen is None:
        with open(pdf_path, "rb") as fh:
            data = fh.read()
        count = data.count(b"/FontFile")
        ok = count > 0
        print(f"  [FONTS] pymupdf unavailable; heuristic FontFile refs={count} "
              f"({'embedded' if ok else 'NOT embedded'})")
        return

    doc = popen(pdf_path)
    seen = {}
    for page_idx in range(doc.page_count):
        for (xref, ext, ftype, basefont, name, encoding) in doc.get_page_fonts(page_idx):
            seen[basefont or name] = ext
    doc.close()

    all_embedded = all(ext != "n/a" for ext in seen.values())
    for basefont, ext in sorted(seen.items()):
        status = "embedded" if ext != "n/a" else "NOT EMBEDDED"
        flag = "" if ext != "n/a" else "  <-- DirectPDF substitution risk"
        print(f"  [FONTS] {basefont}: {ext} ({status}){flag}")
    if all_embedded and seen:
        print("  [FONTS] PASS — 100% of fonts embedded; no external substitution required")
    elif seen:
        print("  [FONTS] FAIL — one or more fonts are not embedded")

    return all_embedded

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

        # Re-enter header zone when encountering court header (e.g. Attachment B)
        if "IN THE CIRCUIT COURT" in text_upper:
            in_header_zone = True

        # Exit header zone immediately upon encountering body preamble or Section I
        if text_upper.startswith("NOW COMES") or re.match(r'^(I|1)\.\s+', text):
            in_header_zone = False

        if in_header_zone:
            # 1. Top Court Header Line (16pt Bold)
            if "IN THE CIRCUIT COURT" in text_upper:
                p['class'] = p.get('class', []) + ['court-header']
                p_html = str(p)
                if "<br" not in p_html.lower() and "JUDICIAL" in p_html and "CIRCUIT" in p_html:
                    new_html = re.sub(r'(JUDICIAL)\s+(CIRCUIT)', r'\1<br/>\2', p_html)
                    new_p = BeautifulSoup(new_html, "html.parser").find("p")
                    if new_p:
                        p.replace_with(new_p)

            # 2. Case Number Line & Judge Line (13pt Regular, Unbolded)
            elif (re.match(r'^\s*(?:Case\s+Nos?\.?|\bNo\.)\s*[\d\w]+', text, re.IGNORECASE) or
                  re.match(r'^\s*Hon\.\s+', text, re.IGNORECASE) or
                  "Gallagher-Chami" in text) and len(text) < 120:
                p['class'] = p.get('class', []) + ['case-number']
                # Strip all inner strong and b tags to force regular weight
                for tag in p.find_all(["strong", "b"]):
                    tag.unwrap()

            # 3. Party Names & vs. (12pt Bold Uppercase)
            elif (any(k in text_upper for k in ["DAVID C. BYERS", "PAULETTA D. DONATELLO", "PETITIONER", "RESPONDENT"]) and
                  "CIRCUIT" not in text_upper and "SUBPOENA" not in text_upper and "NOTICE" not in text_upper and
                  "MOTION" not in text_upper and "CERTIFICATION" not in text_upper):
                p['class'] = p.get('class', []) + ['party-name']
            elif text.strip().lower() in ("vs.", "vs", "v.", "v"):
                p['class'] = p.get('class', []) + ['party-name']

            # 4. Motion / Document Title (14pt Bold) - Only applied inside header zone
            elif any(re.search(r'\b' + kw + r'\b', text_upper) for kw in [
                "MOTION", "PETITION", "ORDER", "RESPONSE", "REPLY", "REQUEST", "NOTICE", "MEMORANDUM", "SUBPOENA", "CERTIFICATION"
            ]) and "CIRCUIT COURT" not in text_upper:
                p['class'] = p.get('class', []) + ['motion-title']
                in_header_zone = False  # Title found; close header zone
        else:
            # 5. Roman Numeral Section Headings (12pt Bold)
            if re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s+', text):
                p['class'] = p.get('class', []) + ['section-heading']

            # 6. Lettered Subsection Headings (12pt Bold)
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
                classes = ['signature-rule']
                if re.search(r"\b(?:Signature|Printed Name|Notary Public)\b", nxt_t, re.IGNORECASE):
                    classes.append('compact-rule')
                hr['class'] = hr.get('class', []) + classes

    # Group signature blocks outside the header zone
    in_header_zone = True
    for elem in list(soup.find_all(["p", "h2", "h3", "h4", "hr"])):
        if elem.name in ("p", "h2", "h3", "h4"):
            text = elem.get_text().strip()
            text_upper = text.upper()
            if (
                text_upper.startswith("NOW COMES")
                or re.match(r'^(?:I{1,3}|IV|V|\d+)\.\s+', text)
                or "ADMINISTRATIVE" in text_upper
                or "GROUP " in text_upper
                or "PRODUCTION RIDER" in text_upper
                or "motion-title" in elem.get("class", [])
            ):
                in_header_zone = False

            if in_header_zone:
                continue

            # Skip if this element is part of a caption
            nxt_sib = elem.find_next_sibling()
            if nxt_sib and nxt_sib.get_text().strip().lower() in ("vs.", "vs", "v.", "v"):
                continue
            if any(term in text.lower() for term in (" vs. ", " vs ", " v. ", " v ")) or ("petitioner" in text.lower() and "respondent" in text.lower()):
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
        # Insert zero-width break opportunities after underscores and slashes
        for cell in table.find_all(["td", "th"]):
            for string in list(cell.strings):
                if "_" in string or "/" in string:
                    new_text = re.sub(r"([_/])", lambda m: m.group(1) + "\u200b", str(string))
                    string.replace_with(new_text)

        headers = [th.get_text().strip() for th in table.find_all("th")]
        col_count = len(headers)
        if col_count == 0:
            first_row = table.find("tr")
            if first_row:
                col_count = len(first_row.find_all(["td", "th"]))

        colgroup = soup.new_tag("colgroup")

        # 1. Two-Column Pleading Tables (Field | Detail, Item | Detail, Date | Change)
        if col_count == 2:
            if headers and "Date" in headers[0]:
                widths = ["20%", "80%"]
            else:
                widths = ["26%", "74%"]
        # 2. Three-Column Tables (Universal Exhibits or Rule 213 Framework)
        elif col_count == 3:
            if headers and "Letter" in headers[0]:
                widths = ["10%", "58%", "32%"]
            elif headers and any("Rule" in h for h in headers):
                widths = ["20%", "40%", "40%"]
            else:
                widths = ["20%", "40%", "40%"]
        # 3. Filing-Specific Exhibits (4 cols)
        elif col_count == 4 and headers and "#" in headers[0]:
            widths = ["6%", "34%", "14%", "46%"]
        # 4. Master Exhibit Catalog (5 cols) -> Mark as high-density
        elif col_count == 5 and headers and ("Letter" in headers[0] or "Exhibit" in headers[1]):
            widths = ["9%", "29%", "30%", "16%", "16%"]
            table['class'] = table.get('class', []) + ['high-density-table']
        # 5. Cross-Reference Matrix (6+ cols) -> Mark as high-density
        elif col_count >= 6:
            first_width = 16
            rem_width = (100 - first_width) / (col_count - 1)
            widths = [f"{first_width}%"] + [f"{rem_width:.1f}%"] * (col_count - 1)
            table['class'] = table.get('class', []) + ['high-density-table']
        else:
            widths = [f"{100 / col_count:.1f}%"] * col_count if col_count > 0 else []

        for w in widths:
            col = soup.new_tag("col", style=f"width: {w};")
            colgroup.append(col)

        table.insert(0, colgroup)

    return soup

def convert_motion_to_pdf(input_file, output_file, margin="0.72", page_numbers=True,
                          gs_sanitize=True, font_family="Arial"):
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            md_text = f.read()

        # Print-safe Unicode normalization (keeps .md source on disk untouched).
        md_text = _sanitize_unicode(md_text)

        # Render Markdown to HTML and apply structural class tagging
        html_raw = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html_tagged = transform_pleading_structure(html_raw)

        # 100% TrueType embedding: register resolved faces via @font-face.
        family, faces = _resolve_font_family(font_family)
        font_face_css = _font_face_css(family, faces) if faces else ""
        font_stack = f'"{family}", Arial, Helvetica, sans-serif' if faces else "Arial, Helvetica, sans-serif"

        page_footer = """
            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-family: %(stack)s;
                font-size: 9pt;
            }
        """ % {"stack": font_stack} if page_numbers else ""

        custom_css = CSS(string=f"""
            @page {{
                size: letter portrait;
                margin: {margin}in;
                {page_footer}
            }}

            {font_face_css}

            body {{
                font-family: {font_stack};
                font-size: 11pt;
                line-height: 1.3;
                color: #000000;
                margin-top: 0;
                padding-top: 0;
            }}

            p {{
                margin-top: 0;
                margin-bottom: 8pt;
                font-size: 11pt;
                line-height: 1.3;
                text-align: justify;
            }}

            /* 1. Main Court Header (16pt Bold) */
            .court-header, .court-header strong, .court-header b {{
                font-size: 16pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 0 !important;
                margin-bottom: 14pt !important;
                line-height: 1.2 !important;
            }}

            /* Party Names (12pt Bold Uppercase) */
            .party-name, .party-name strong, .party-name b {{
                font-size: 12pt !important;
                font-weight: bold !important;
                text-align: left !important;
                margin-top: 0 !important;
                margin-bottom: 2pt !important;
                line-height: 1.2 !important;
            }}

            /* 2. Case Information Line (13pt Regular, Strictly Unbolded) */
            .case-number, .case-number * {{
                font-size: 13pt !important;
                font-weight: normal !important;
                text-decoration: none !important;
                text-align: left !important;
                margin-top: 2pt !important;
                margin-bottom: 4pt !important;
            }}

            /* 3. Document Title (14pt Bold) */
            .motion-title, .motion-title strong, .motion-title b {{
                font-size: 14pt !important;
                font-weight: bold !important;
                text-align: left !important;
                text-transform: uppercase !important;
                margin-top: 10pt !important;
                margin-bottom: 12pt !important;
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

            /* Lists & Body Formatting (11pt Default) */
            ul, ol {{
                margin-top: 0;
                margin-bottom: 8pt;
                padding-left: 20pt;
            }}

            li {{
                margin-bottom: 4pt;
                font-size: 11pt;
                line-height: 1.3;
                overflow-wrap: break-word;
                hyphens: auto;
            }}

            li p {{
                margin-top: 0 !important;
                margin-bottom: 2pt !important;
            }}

            li li, li li li {{
                padding-left: 10pt;
                overflow-wrap: break-word;
                hyphens: auto;
            }}

            strong, li strong {{
                font-size: 11pt;
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
                margin-top: 32pt !important;
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
                width: 280px !important;
                margin-top: 24pt !important; /* Space above rule for physical signature */
                margin-bottom: 4pt !important;
                margin-left: 0 !important;
                page-break-after: avoid !important;
                break-after: avoid !important;
            }}

            hr.signature-rule.compact-rule {{
                margin-top: 16pt !important;
                margin-bottom: 2pt !important;
            }}

            /* Standard Pleading Table Styling (Uniform 12pt Pleading Standard) */
            table {{
                width: 100% !important;
                table-layout: fixed !important;
                border-collapse: collapse !important;
                margin-top: 8pt !important;
                margin-bottom: 12pt !important;
                font-size: 12pt !important;
                line-height: 1.3 !important;
            }}

            thead {{
                display: table-header-group !important;
            }}

            tr {{
                page-break-inside: auto !important;
                break-inside: auto !important;
            }}

            th {{
                background-color: #f2f2f2 !important;
                font-weight: bold !important;
                text-align: left !important;
                padding: 4pt 6pt !important;
                border: 0.5pt solid #777 !important;
                font-size: 12pt !important;
                vertical-align: bottom !important;
            }}

            td {{
                padding: 4pt 6pt !important;
                border: 0.5pt solid #aaa !important;
                vertical-align: top !important;
                font-size: 12pt !important;
                overflow-wrap: break-word !important;
                word-break: normal !important;
            }}

            /* Ensure all font styling within standard tables inherits uniform 12pt */
            td *, th *, td strong, th strong, td p, th p {{
                font-size: inherit !important;
            }}

            td strong, th strong {{
                font-weight: bold !important;
            }}

            /* High-Density Index/Catalog Tables Only (5+ columns) */
            table.high-density-table,
            table.high-density-table th,
            table.high-density-table td {{
                font-size: 8.5pt !important;
                line-height: 1.25 !important;
                padding: 3pt 4.5pt !important;
            }}

            table.high-density-table th:first-child,
            table.high-density-table td:first-child {{
                text-align: center !important;
                white-space: nowrap !important;
            }}

            table.high-density-table td code,
            table.high-density-table th code {{
                font-family: inherit !important;
                font-size: 8pt !important;
                background-color: #f8f8f8;
                padding: 1pt 2pt;
                border: 0.5pt solid #e0e0e0;
            }}
        """)

        HTML(string=html_tagged).write_pdf(output_file, stylesheets=[custom_css])
        print(f"  [SUCCESS] Refactored Motion PDF rendered -> {output_file}")

        if gs_sanitize:
            _ghostscript_sanitize_pdf(output_file)

        _audit_fonts(output_file)
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
    parser.add_argument("--no-gs-sanitize", action="store_true",
                        help="Skip the Ghostscript prepress EmbedAllFonts/SubsetFonts pass")
    parser.add_argument("--font-family", default="Arial",
                        help="Embedded TrueType sans-serif family: Arial (default), Liberation Sans, DejaVu Sans")

    args = parser.parse_args()
    output_pdf = args.output or args.input.rsplit(".", 1)[0] + ".pdf"
    convert_motion_to_pdf(args.input, output_pdf, margin=str(args.margin),
                          page_numbers=not args.no_page_numbers,
                          gs_sanitize=not args.no_gs_sanitize,
                          font_family=args.font_family)
