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
Shared utilities for legal document processing.
Used by both sync_legal_docs.py and generate_response_sheet.py
"""

import os
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import pdfplumber

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / '.env')


# ---------------------------------------------------------------------------
# Shared PDF processing utilities
# ---------------------------------------------------------------------------

def is_readable(text):
    """Check if text contains enough readable content.

    Strips page break markers, OCR artifacts, and form lines before
    counting words to avoid false positives from separator-only text
    (e.g. a scanned PDF that only produces '--- Page Break ---' markers).
    """
    # Remove page break markers and structural separators
    cleaned = re.sub(r'---\s*Page\s*Break\s*---', '', text)
    cleaned = re.sub(r'#+\s*Structural\s*Path\s*Context.*?---', '', cleaned, flags=re.DOTALL)
    # Remove common OCR artifacts and form lines
    cleaned = re.sub(r'[\u25c8\u25c6\u2610\u2611\u2612\u2713\u2717\u2714Xx_\n\r\t]+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if len(cleaned.strip()) < 50:
        return False
    # Look for actual words
    words = re.findall(r'\b[a-zA-Z]{3,}\b', cleaned.lower())
    if len(words) < 25:
        return False
    return True


def is_scanned_pdf(pdf_path):
    """Detects if a PDF is an image-based scan vs born-digital."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            sample_text = ""
            # Check first few pages
            for page in pdf.pages[:3]:
                sample_text += page.extract_text() or ""
            return len(sample_text.strip()) < 50
    except Exception:
        return True


def clean_legal_artifacts(text):
    """
    Removes common legal form 'noise' like underscores used for
    handwriting lines and excessive whitespace.
    """
    # 1. Remove underscores inside words (e.g., _D_e_K_a_l_b_ -> DeKalb)
    text = re.sub(r'_(?=[a-zA-Z0-9])|(?<=[a-zA-Z0-9])_', '', text)

    # 2. Remove long runs of underscores used for blank lines
    text = re.sub(r'_{2,}', ' ', text)

    # 3. Fix "wide text" from OCR (e.g., "D e K a l b" -> "DeKalb")
    def fix_wide_text(m):
        return ''.join(m.group(0).split())

    text = re.sub(r'\b([A-Za-z])(\s+[A-Za-z])+\b',
                lambda m: fix_wide_text(m), text)

    # 4. Normalize whitespace on a per-line basis, but preserve newlines
    lines = text.split('\n')
    cleaned_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]
    text = '\n'.join(cleaned_lines)

    return text


def extract_form_fields(pdf_path):
    """Extract form field data from a PDF."""
    form_data = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    fields = page.get_form_fields()
                    if fields:
                        for field in fields:
                            name = field.get("name", f"field_{page_num}")
                            # Get value - handle both 'value' and 'export_value'
                            value = field.get("value") or field.get("export_value", "")
                            if value:
                                form_data[name] = value
                except Exception:
                    pass
    except Exception:
        pass
    return form_data


def get_local_ocr():
    """Get or create PaddleOCR instance for local OCR."""
    global _local_ocr
    if _local_ocr is None:
        try:
            from paddleocr import PaddleOCR
            # Suppress paddleocr logging
            import logging
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            _local_ocr = PaddleOCR(lang='en', use_angle_cls=True, show_log=False)
        except ImportError:
            print("  -> PaddleOCR not installed, falling back to pytesseract")
            _local_ocr = "pytesseract"
    return _local_ocr


_local_ocr = None


def ocr_pdf_images(pdf_path):
    """OCR fallback using PaddleOCR or pytesseract."""
    text_parts = []
    try:
        import fitz
        ocr = get_local_ocr()
        
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = f"/tmp/ocr_page_{page_num}.png"
            pix.save(img_path)
            
            if ocr == "pytesseract":
                from PIL import Image
                text = pytesseract.image_to_string(Image.open(img_path))
                if text.strip():
                    text_parts.append(text.strip())
            else:
                result = ocr.ocr(img_path)
                if result and result[0]:
                    # Extract text from boxes
                    texts = [line[1][0] for line in result[0]]
                    text_parts.extend(texts)
            
            # Clean up temp file
            if os.path.exists(img_path):
                os.remove(img_path)
        doc.close()
    except Exception as e:
        print(f"  -> OCR error: {e}")
    return "\n".join(text_parts)


def extract_text_from_pdf(pdf_path):
    """
    Tiered PDF text extraction:
    1. Try pdftotext (best for layout preservation)
    2. Fallback to pdfplumber
    3. Fallback to OCR if scanned or poor results
    """
    text = ""
    pdf_path = Path(pdf_path)
    
    # Try pdftotext first
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', str(pdf_path), '-'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            text = result.stdout
    except Exception:
        pass
    
    # Fallback to pdfplumber
    if not text.strip():
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                text_parts = [p.extract_text() for p in pdf.pages]
                text = "\n\n--- Page Break ---\n\n".join(filter(None, text_parts))
        except Exception:
            pass
    
    # If still poor quality or empty, try OCR
    if not is_readable(text) or not text.strip():
        print(f"  -> Low quality text extraction, trying OCR for {pdf_path.name}...")
        text = ocr_pdf_images(pdf_path)
    
    return text


# ---------------------------------------------------------------------------
# Boilerplate patterns
# ---------------------------------------------------------------------------

BOILERPLATE_PATTERNS = [
    re.compile(r'Approved by the Conference of Chief Judges', re.I),
    re.compile(r'Forms are free at', re.I),
    re.compile(r'Page \d+ of \d+', re.I),
    re.compile(r'IN THE STATE OF ILLINOIS', re.I),
    re.compile(r'Circuit Court.*County', re.I),
    re.compile(r'Enter the case information as it appears', re.I),
    re.compile(r'Explain in a few words what you are asking', re.I),
    re.compile(r'Where You Are Filing the Case', re.I),
    re.compile(r'Who started the case', re.I),
    re.compile(r'Who the case was filed against', re.I),
    re.compile(r'Check one box', re.I),
    re.compile(r'This should match the title you write', re.I),
    re.compile(r'Approved.*\d{4}\.\d{2}\.\d{2}', re.I),
    re.compile(r'State of Illinois.*Circuit Court', re.I),
    re.compile(r'Placeholder.*case number', re.I),
    re.compile(r'ATJ \d+\.\d+', re.I),
    re.compile(r'ilcourts\.info', re.I),
    re.compile(r'Find your Circuit Clerk', re.I),
    re.compile(r'After you fill out your forms', re.I),
    re.compile(r'file them with the circuit clerk', re.I),
    re.compile(r'send your forms to the other people', re.I),
    re.compile(r'NEXT STEP FOR PERSON', re.I),
    re.compile(r'Learn more about each step', re.I),
    re.compile(r'illinois court help', re.I),
    re.compile(r'illinois legal aid online', re.I),
    re.compile(r'You may also find more information', re.I),
    re.compile(r'location of your local legal self-help center', re.I),
    re.compile(r'If there are any words or terms that you do not understand', re.I),
    re.compile(r'ilcourthelp\.gov', re.I),
    re.compile(r'ilao\.info', re.I),
    re.compile(r'under illinois supreme court rule', re.I),
    re.compile(r'my signature means that', re.I),
    re.compile(r'i read the document', re.I),
    re.compile(r'i have been informed and believe it is true', re.I),
]

BLOCKLIST_PATTERNS = [
    re.compile(r'PROOF\s+OF\s+DELIVERY', re.I),
    re.compile(r'CERTIFICATE\s+OF\s+SERVICE', re.I),
    re.compile(r'Attorney\s+Number', re.I),
    re.compile(r'Law\s+Firm', re.I),
    re.compile(r'EFSP', re.I),
    re.compile(r'Street.*Apt\.?\s*#', re.I),
    re.compile(r'City\s+State\s+Zip\s+Code', re.I),
    re.compile(r'Instructions', re.I),
    re.compile(r'icourts\.info', re.I),
]


def scrub_boilerplate(text):
    """Remove known form instructions and boilerplate text."""
    if not text:
        return ""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        if any(pat.search(line) for pat in BOILERPLATE_PATTERNS):
            continue
        # Skip lines that are just form field underscores/boxes
        if re.match(r'^\s*[._\u25fb\u25a1\u2610]{3,}\s*$', line):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


# ---------------------------------------------------------------------------
# Metadata extraction patterns
# ---------------------------------------------------------------------------

IL_CASE_PATTERN = re.compile(r'\b(\d{2,4}[A-Z]{2}\d{5,12})\b')

PARTY_PATTERNS = [
    # Match "PLAINTIFF/PETITIONER OR IN RE: Name"
    re.compile(r'(?:PLAINTIFF|PETITIONER|IN RE)\s*[:\s]+([A-Z][A-Za-z\s,\.]{2,50})(?:\s+Who|First,|$)', re.I),
    # Match "Who started the case. Name"
    re.compile(r'Who started the case\.\s*([A-Z][A-Za-z\s,\.]{2,50})(?:\s+Who|First,|$)', re.I),
    # Match "Who the case was filed against. Name"
    re.compile(r'Who the case was filed against\.\s*([A-Z][A-Za-z\s,\.]{2,50})(?:\s+First,|$)', re.I),
]

TITLE_PATTERNS = [
    # Match "Motion to: _TEXT_" (user input)
    re.compile(r'Motion to:\s*(_[A-Z_\s]+_)(?:\s+2\.|Check|$)', re.I),
    # Match "MOTION TO RELOCATE..." in form header
    re.compile(r'MOTION\s+TO\s+([A-Z][A-Za-z\s]{5,100})(?:\s+2\.|Check|$)', re.I),
    # Match "NOTICE OF..."
    re.compile(r'NOTICE\s+OF\s+([A-Z][A-Za-z\s]{5,100})(?:\s+|$)', re.I),
    # Match "PETITION FOR..."
    re.compile(r'PETITION\s+FOR\s+([A-Z][A-Za-z\s]{5,100})(?:\s+|$)', re.I),
]

def extract_metadata(text, state_code="IL"):
    """
    Extract metadata (case number, parties, title) from legal text.
    Returns dict with keys: case_number, parties, title, case_header
    """
    metadata = {
        'case_number': '',
        'parties': [],
        'title': '',
        'case_header': ''
    }
    
    if not text:
        return metadata

    # Extract case number
    case_match = IL_CASE_PATTERN.search(text)
    if case_match:
        metadata['case_number'] = case_match.group(1)
    
    # Extract parties
    for pattern in PARTY_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            name = match.strip()
            if name and len(name) > 2 and name not in metadata['parties']:
                # Clean up names
                name = re.sub(r'[,_;]', '', name)
                name = re.sub(r'\s+', ' ', name).strip()
                if name and len(name) < 100:  # Avoid capturing whole paragraphs
                    metadata['parties'].append(name)
    
    # Extract title
    for pattern in TITLE_PATTERNS:
        match = pattern.search(text)
        if match:
            title = match.group(1).strip()
            if title and 5 < len(title) < 200:
                metadata['title'] = title.upper()
                break
    
    # Build case header
    parts = []
    if metadata['case_number']: parts.append(metadata['case_number'])
    if metadata['title']: parts.append(metadata['title'])
    metadata['case_header'] = " - ".join(parts)
    
    return metadata


def extract_dates(text):
    """Extract all unique dates from legal text."""
    if not text:
        return []
    
    date_patterns = [
        re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),
        re.compile(r'\b\d{4}-\d{1,2}-\d{1,2}\b'),
        re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b', re.I),
    ]
    
    dates = []
    for pattern in date_patterns:
        dates.extend(pattern.findall(text))
    return list(set(dates))


# ---------------------------------------------------------------------------
# Blank form comparison
# ---------------------------------------------------------------------------

def load_blank_form_text(state_code="IL"):
    """
    Load blank form text for comparison.
    Returns set of normalized lines from the blank form.
    """
    from state_form_config import get_state_config, get_blank_form_path
    
    blank_lines = set()
    config = get_state_config(state_code)
    
    paths_to_try = []
    if config:
        if config.get("form_path"): paths_to_try.append(Path(config["form_path"]))
        if config.get("additional_form_path"): paths_to_try.append(Path(config["additional_form_path"]))

    for path in paths_to_try:
        # Try MD version first
        md_path = path.with_suffix(".md")
        if md_path.exists():
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        norm = re.sub(r'\s+', ' ', line.strip().lower())
                        if len(norm) > 3:
                            blank_lines.add(norm)
            except Exception:
                pass
        
        # Then try PDF
        if path.exists():
            try:
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            for line in text.split('\n'):
                                norm = re.sub(r'\s+', ' ', line.strip().lower())
                                if len(norm) > 3:
                                    blank_lines.add(norm)
            except Exception:
                pass
                
    return blank_lines


def clean_claim_text(text, blank_lines=None):
    """
    Clean individual claim text by removing boilerplate embedded within.
    Removes: checkbox text, clerk footers, form instructions, URLs.
    If blank_lines provided, also removes form labels.
    """
    if not text:
        return ""
        
    import unicodedata
    # Normalize unicode characters
    text = unicodedata.normalize('NFKC', text)
    
    # Remove checkbox attachments (✔ I need more room... or ✓ I have filled out...)
    text = re.sub(r'[✓✔❌☑☒]\s*(I need more room|I have filled out|Additional Page).*?(?=\.|$)', '', text, flags=re.IGNORECASE)
    
    # Remove clerk footers - pattern: "Accepted: 4/29/2026 8:27 AM Reviewed By: EH Env#37816100"
    text = re.sub(r'Accepted:\s*[\d/]+\s*[\d:]+\s*[AP]M\s*Reviewed By:\s*\w+\s*Env#\d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Reviewed By:\s*\w+\s*Env#\d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Env#\d+', '', text)
    
    # Remove case numbers like "25FA152" that appear after clerk footers
    text = re.sub(r'\d+[A-Z]{2}\d+\s*', '', text)
    
    # Remove common form footers
    text = re.sub(r'Under Illinois Supreme Court Rule.*?(?=\.|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'In some counties, you may get the court date.*?(?=\.|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'After you fill out your forms.*?(?=\.|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'Find your Circuit Clerk.*?(?=\.|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\S+\.info/\S+', '', text)
    
    # Remove form labels if blank lines provided
    if blank_lines:
        text_lower = text.lower()
        for blank_line in blank_lines:
            if len(blank_line) > 15:
                if blank_line in text_lower:
                    idx = text_lower.find(blank_line)
                    text = text[:idx] + text[idx + len(blank_line):]
                    text_lower = text.lower()
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def split_text_into_sentences(text):
    """
    Split text into atomic sentences using a more robust regex.
    Handles various sentence boundaries and abbreviations.
    """
    if not text or len(text.strip()) < 15:
        return []

    # 1. Normalize whitespace and clean up some common OCR errors
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'([a-z])\s+([A-Z])', r'\1. \2', text) # Fix run-ons like "sentenceA new sentence"

    # 2. Split into sentences using a regex that handles abbreviations
    # This regex splits on '.', '!', '?' followed by a space,
    # but not if the period is preceded by a known abbreviation or a single capital letter.
    # It also splits on newlines and semicolons.
    abbreviations = r'(?<!\b(?:[A-Z][a-z]?\. |(?:Mr|Mrs|Ms|Dr|Sr|Jr|vs|e\.g|i\.e)\.))'
    sentence_enders = r'(?<=[.!?])\s+|\n+|;'
    
    # We combine them. We look for a sentence end, but the negative lookbehind
    # ensures we don't split on an abbreviation.
    sentences = re.split(f'{abbreviations}{sentence_enders}', text)

    # 3. Clean up the results
    final_sentences = []
    for sent in sentences:
        if not sent:
            continue
        sent = sent.strip()
        if len(sent) >= 15:
            final_sentences.append(sent)

    return final_sentences


def is_form_instruction(text, blank_lines=None, threshold=0.6):
    """
    Check if text is likely a form instruction.
    """
    if not text:
        return False
    
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    
    # Substring check against blank form lines
    if blank_lines:
        for blank_line in blank_lines:
            if normalized in blank_line or blank_line in normalized:
                return True
        
        # Word-level overlap with blank form
        words_text = set(normalized.split())
        if words_text:
            for blank_line in blank_lines:
                words_blank = set(blank_line.split())
                if words_blank:
                    overlap = len(words_text & words_blank)
                    similarity = overlap / max(len(words_text), len(words_blank))
                    if similarity > threshold:
                        return True
    
    # Known form label patterns
    form_labels = [
        r'^\s*county:?\s*_{2,}',
        r'^\s*case number:?\s*_{2,}',
        r'^\s*plaintiff.*:?\s*_{2,}',
        r'^\s*defendant.*:?\s*_{2,}',
        r'^\s*name:?\s*_{2,}',
        r'^\s*address:?\s*_{2,}',
        r'^\s*phone.*:?\s*_{2,}',
        r'^\s*email.*:?\s*_{2,}',
        r'^\s*signature.*:?\s*_{2,}',
        r'^\s*motion to:?\s*_{2,}',
        r'^\s*explain.*:?\s*_{2,}',
        r'^\s*i am.*:?\s*_{2,}',
        r'^\s*enter the case',
        r'^\s*who started the case',
        r'^\s*who the case was filed against',
        r'^\s*date:?\s*_{2,}',
        r'^\s*time:?\s*_{2,}',
        r'^\s*print name:?\s*_{2,}',
        r'^\s*for court use only',
        r'^\s*clerk\'s certification',
    ]
    for pattern in form_labels:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
            
    return False
