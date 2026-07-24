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

"""
Centralized document processing utilities for Hiver.
This module contains the core logic for converting PDFs to Markdown.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path
import pdfplumber
from dotenv import load_dotenv
load_dotenv()

from markitdown import MarkItDown
import fitz

# Add scripts directory to Python path for imports
import sys
import os
scripts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# It's better to handle the absence of paddleocr gracefully
try:
    from paddleocr import PaddleOCR
    _local_ocr = None
    def get_local_ocr():
        global _local_ocr
        if _local_ocr is None:
            _local_ocr = PaddleOCR(lang='en')
        return _local_ocr
except ImportError:
    _local_ocr = None
    def get_local_ocr():
        return None

from legal_utils import (
    is_readable, extract_form_fields, extract_text_from_pdf
)

def ocr_pdf_images(pdf_path):
    """OCR scanned PDF pages with automatic rotation correction.

    For each page:
    1. Render at 2x resolution
    2. Detect orientation via Tesseract OSD
    3. Rotate image to upright if needed
    4. Run Tesseract OCR (language: eng)
    5. Collect extracted text with page breaks

    Falls back to PaddleOCR if Tesseract is unavailable.
    """
    text_parts = []
    try:
        from PIL import Image
        import io as _io
    except ImportError:
        Image = None

    try:
        doc = fitz.open(pdf_path)
        total = doc.page_count
        MATRIX = fitz.Matrix(2, 2)

        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(matrix=MATRIX)

            # Convert to PIL Image for rotation
            if Image:
                img = Image.open(_io.BytesIO(pix.tobytes("png")))

                # Detect orientation via Tesseract OSD
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    pix.save(tmp.name)
                    tmp_path = tmp.name
                try:
                    result = subprocess.run(
                        ["tesseract", tmp_path, "-", "--psm", "0"],
                        capture_output=True, timeout=15,
                    )
                    stdout = result.stdout.decode("utf-8", errors="replace")
                    orient = 0
                    for line in stdout.split("\n"):
                        if "Orientation in degrees" in line:
                            orient = int(line.split(":")[1].strip())
                            break

                    if orient != 0:
                        fix_angle = (360 - orient) % 360
                        img = img.rotate(fix_angle, expand=True)
                        if page_num % 20 == 0:
                            print(f"     Page {page_num+1}: rotated {orient}° -> fixed")
                except Exception:
                    pass
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

                # Save corrected image and OCR with Tesseract
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    img.save(tmp.name)
                    ocr_path = tmp.name
                try:
                    result = subprocess.run(
                        ["tesseract", ocr_path, "-", "--psm", "6", "-l", "eng"],
                        capture_output=True, timeout=30,
                    )
                    page_text = result.stdout.decode("utf-8", errors="replace").strip()
                    if page_text:
                        text_parts.append(page_text)
                except Exception:
                    pass
                finally:
                    if os.path.exists(ocr_path):
                        os.unlink(ocr_path)
            else:
                # Fallback: PaddleOCR without rotation
                ocr = get_local_ocr()
                if not ocr:
                    print("  -> No OCR engine available (need Tesseract or PaddleOCR)")
                    return ""
                img_path = f"/tmp/ocr_page_{page_num}.png"
                pix.save(img_path)
                result = ocr.ocr(img_path)
                if result and result[0]:
                    r = result[0]
                    texts = r.get('rec_texts', [])
                    text_parts.extend(texts)

            if page_num % 20 == 0 and page_num > 0:
                print(f"     Processed {page_num+1}/{total} pages...")

        doc.close()
    except Exception as e:
        print(f"  -> OCR error: {e}")

    return "\n\n--- Page Break ---\n\n".join(text_parts)

def clean_form_field_spacing(text: str) -> str:
    """Remove underscores that pdftotext inserts between characters
    in fillable PDF form fields. Pattern: _c_h_a_r_a_c_t_e_r_s_
    Iterates to handle adjacent chars (e.g. D__o from D and o in same field)."""
    # Pass 1: strip underscores between individual chars  _c_ → c
    while True:
        cleaned = re.sub(r"_([A-Za-z0-9.])_", r"\1", text)
        if cleaned == text:
            break
        text = cleaned
    # Pass 2: strip underscores at form-field word boundaries
    # e.g. "David_ " → "David ", " _C." → "C.", "D._ " → "D. "
    text = re.sub(r"(?<=[A-Za-z0-9.])_(?=\s|$)", r"", text)
    text = re.sub(r"(?<=\s)_(?=[A-Za-z0-9.])", r"", text)
    # Pass 3: strip underscores between adjacent letters from tight form-field spacing
    # e.g. "D_o" → "Do", "Fam__ily" → "Family"
    text = re.sub(r"__", r"_", text)  # collapse double underscores first
    text = re.sub(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])", r"", text)
    return text


def build_markdown_with_form(text, form_data, original_name="", virtual_path="", ocr_status="good"):
    lines = []
    
    name = original_name or Path(virtual_path).name if virtual_path else original_name
    vpath = virtual_path or original_name
    
    lines.append("---")
    lines.append(f"original_name: {name}")
    lines.append(f"virtual_path: {vpath}")
    lines.append(f"ocr_status: {ocr_status}")
    lines.append("---")
    lines.append("")
    
    if vpath and "/" in vpath:
        parts = vpath.split("/")
        path_chain = " -> ".join(
            f"📁 {p}" if i < len(parts) - 1 else f"📄 {p}"
            for i, p in enumerate(parts)
        )
        lines.append("# Structural Path Context")
        lines.append(path_chain)
        lines.append("")
        lines.append("---")
        lines.append("")
    
    if ocr_status == "image_only":
        lines.append("> **⚠️ OCR REQUIRED**: This document is image-based and could not be read.")
        lines.append("> Submit for AI Vision OCR processing.")
        lines.append("")
    elif ocr_status == "needs_review":
        lines.append("> **⚠️ LOW TEXT QUALITY**: This document may have incomplete text extraction.")
        lines.append("> Review and submit for AI Vision OCR if needed.")
        lines.append("")
    
    if text:
        lines.append(text.strip())
    if form_data:
        lines.append("\n## Form Fields\n")
        for key, value in form_data.items():
            lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)

def get_llm_converter():
    import google.genai as genai
    from django.conf import settings
    api_key = getattr(settings, "GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        client = genai.Client(api_key=api_key)
        return client
    except Exception as e:
        print(f"Warning: Could not initialize Gemini client: {e}")
        return None

def fix_pdf_rotation(pdf_path, sample_interval=5):
    """Detect and correct rotated pages in a scanned PDF using Tesseract OSD.

    Samples every `sample_interval` pages for speed. If any sampled page
    is rotated, ALL pages are checked and corrected. Sets the PDF page
    rotation metadata so downstream tools (pdftotext, Vision API) render
    pages upright. The original PDF bytes are preserved — only metadata
    changes, keeping file size minimal.

    Returns path to a corrected temp PDF, or the original path if no
    rotation was found.

    Requires: tesseract with osd language pack, PyMuPDF (fitz).
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    total = doc.page_count

    if total == 0:
        doc.close()
        return str(pdf_path)

    MATRIX = fitz.Matrix(2, 2)  # 2x zoom for OSD accuracy

    def _detect_orientation(page):
        """Use Tesseract OSD to detect page orientation in degrees."""
        pix = page.get_pixmap(matrix=MATRIX)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pix.save(tmp.name)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["tesseract", tmp_path, "-", "--psm", "0"],
                capture_output=True, timeout=15,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            for line in stdout.split("\n"):
                if "Orientation in degrees" in line:
                    return int(line.split(":")[1].strip())
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return 0

    # Phase 1: Quick scan — check every sample_interval-th page
    sample_indices = list(range(0, total, sample_interval))
    needs_full_scan = False
    for idx in sample_indices:
        orient = _detect_orientation(doc[idx])
        if orient != 0:
            needs_full_scan = True
            break

    if not needs_full_scan:
        doc.close()
        return str(pdf_path)

    # Phase 2: Check ALL pages and build rotation map
    print(f"  -> Rotation detected; scanning all {total} pages...")
    rotations = {}
    for idx in range(total):
        rotations[idx] = _detect_orientation(doc[idx])
        if idx % 30 == 0 and idx > 0:
            print(f"     Scanned {idx+1}/{total}...")

    rotated_count = sum(1 for v in rotations.values() if v != 0)
    if rotated_count == 0:
        doc.close()
        return str(pdf_path)

    print(f"  -> Fixing {rotated_count}/{total} rotated pages (metadata)...")

    # Phase 3: Set rotation metadata on each page
    # Tesseract reports the CW rotation needed to read the text.
    # PDF set_rotation() sets the display rotation — we set it to the
    # detected value so renderers rotate the page to upright.
    for idx, orient in rotations.items():
        if orient != 0:
            page = doc[idx]
            page.set_rotation(orient)

    # Save corrected PDF to temp file (metadata-only change, small file)
    tmpdir = tempfile.gettempdir()
    corrected_path = Path(tmpdir) / f"corrected_{pdf_path.name}"
    doc.save(str(corrected_path))
    doc.close()
    print(f"  -> Saved corrected PDF: {corrected_path.name} ({os.path.getsize(corrected_path) // 1024}KB)")
    return str(corrected_path)


def convert_pdf_to_markdown(pdf_path, original_name="", virtual_path=""):
    pdf_path = Path(pdf_path)
    md_path = pdf_path.with_suffix(".md")

    form_data = {}
    text = ""
    llm_client = get_llm_converter()

    try:
        try:
            result = subprocess.run(
                ['pdftotext', '-layout', str(pdf_path), '-'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                text = result.stdout
                # Clean form-field underscore artifacts
                text = clean_form_field_spacing(text)
        except Exception:
            pass

        if not text:
            try:
                with pdfplumber.open(str(pdf_path)) as pdf:
                    text_parts = [p.extract_text_simple() for p in pdf.pages]
                    text = "\n\n--- Page Break ---\n\n".join(text_parts)
                text = clean_form_field_spacing(text)
            except Exception:
                pass

        try:
            form_data = extract_form_fields(str(pdf_path))
        except Exception:
            pass

        if not is_readable(text):
            print(f"  -> Low text quality, attempting OCR...")
            # Fix rotated pages before OCR — scanned medical records often
            # have mixed portrait/landscape pages that confuse text extraction
            ocr_pdf = str(pdf_path)
            try:
                from legal_utils import is_scanned_pdf
                if is_scanned_pdf(str(pdf_path)):
                    print(f"  -> Scanned PDF detected, checking page rotation...")
                    ocr_pdf = fix_pdf_rotation(str(pdf_path))
            except Exception as e:
                print(f"  -> Rotation check skipped: {e}")

            if llm_client:
                try:
                    print(f"  -> Using Vision API...")
                    uploaded = llm_client.files.upload(file=ocr_pdf)
                    result = llm_client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[uploaded, "Extract all text from this document."]
                    )
                    text = result.text if hasattr(result, 'text') else str(result)
                    # If Vision API returned unusable text, fall back to Tesseract
                    if not is_readable(text):
                        print(f"  -> Vision API returned low-quality text, falling back to Tesseract OCR...")
                        text = ocr_pdf_images(ocr_pdf)
                except Exception as e:
                    print(f"  -> Vision failed: {e}, trying local OCR...")
                    text = ocr_pdf_images(ocr_pdf)
            else:
                print(f"  -> Using local Tesseract OCR...")
                text = ocr_pdf_images(ocr_pdf)

        if is_readable(text):
            ocr_status = "good"
            print(f"  -> Text quality: good")
        elif len(text.strip()) < 50:
            ocr_status = "image_only"
            print(f"  -> Text quality: IMAGE ONLY — OCR still needed")
        else:
            ocr_status = "needs_review"
            print(f"  -> Text quality: LOW — review recommended")

        combined = build_markdown_with_form(text, form_data, original_name, virtual_path, ocr_status)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(combined)

        return md_path
    except Exception as e:
        raise e


def process_document(file_path: str, output_dir: str = None, original_name: str = "", virtual_path: str = "") -> str:
    """
    Router pattern for filetype-based processing.
    
    Routes to the appropriate processing script based on file extension.
    
    Args:
        file_path (str): Absolute path to the uploaded file
        output_dir (str, optional): Output directory. Defaults to same as input.
        original_name (str): Original filename from the upload
        virtual_path (str): Relative directory path from webkitRelativePath
    
    Returns:
        str: Path to the processed/converted file
    
    Supported types:
        .pdf -> convert_pdf_to_markdown() -> .md
        .json -> (future: JSON to Markdown for phone records)
        .html, .eml -> (future: Email/HTML to Markdown)
        .doc, .docx -> (future: Word to Markdown)
        * -> Return original path (no conversion)
    """
    import os
    from pathlib import Path
    
    file_path = Path(file_path)
    file_ext = file_path.suffix.lower()
    
    if file_ext == '.pdf':
        md_path = convert_pdf_to_markdown(str(file_path), original_name, virtual_path)
        return md_path
    
    if file_ext == '.json':
        return str(file_path)
    
    if file_ext in ['.html', '.htm', '.eml']:
        return str(file_path)
    
    if file_ext in ['.doc', '.docx']:
        return str(file_path)
    
    return str(file_path)
