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
    text_parts = []
    ocr = get_local_ocr()
    if not ocr:
        print("  -> PaddleOCR not available. Skipping local OCR.")
        return ""

    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = f"/tmp/ocr_page_{page_num}.png"
            pix.save(img_path)

            result = ocr.ocr(img_path)
            if result and result[0]:
                r = result[0]
                texts = r.get('rec_texts', [])
                text_parts.extend(texts)
        doc.close()
    except Exception as e:
        print(f"  -> Local OCR error: {e}")
    return "\n".join(text_parts)

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
        except Exception:
            pass

        if not text:
            try:
                with pdfplumber.open(str(pdf_path)) as pdf:
                    text_parts = [p.extract_text_simple() for p in pdf.pages]
                    text = "\n\n--- Page Break ---\n\n".join(text_parts)
            except Exception:
                pass

        try:
            form_data = extract_form_fields(str(pdf_path))
        except Exception:
            pass

        if not is_readable(text):
            print(f"  -> Low text quality, attempting OCR...")
            if llm_client:
                try:
                    print(f"  -> Using Vision API...")
                    uploaded = llm_client.files.upload(file=str(pdf_path))
                    result = llm_client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[uploaded, "Extract all text from this document."]
                    )
                    text = result.text if hasattr(result, 'text') else str(result)
                except Exception as e:
                    print(f"  -> Vision failed: {e}, trying local OCR...")
                    text = ocr_pdf_images(str(pdf_path))
            else:
                print(f"  -> Using local PaddleOCR...")
                text = ocr_pdf_images(str(pdf_path))

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
