# Scripts Reference — dc13_hive/scripts/

> Generated 2026-06-13. Run `python3 -c "import this"` or open a script's docstring for details.

## Quick Index

| Script | What it does | Typical invocation |
|--------|-------------|-------------------|
| `ingest.py` | Full pipeline: PDF→MD → classify → route → RAG sync | `uv run ingest.py --auto --rag --filemap` |
| `sync_legal_docs.py` | **SINGLE source of truth** for PDF→MD conversion | `uv run sync_legal_docs.py` |
| `timeline_to_pdf.py` | Markdown → print-ready PDF (replaces LibreOffice workflow) | `uv run timeline_to_pdf.py file.md --margin 0.72` |
| `build_binder_pdf.py` | Combine PDFs → binder with page numbers + index | `uv run build_binder_pdf.py BINDER -p -i` |
| `build_thread_master.py` | SMS + Gmail → consolidated THREAD_MASTER JSON | `uv run build_thread_master.py --contact <name> ...` |
| `json_to_transcript.py` | THREAD_MASTER JSON → legal transcript HTML | `uv run json_to_transcript.py -i input.json -o output.html` |
| `extract_all_dates.py` | Scan .md/.txt for dates → DATE_INDEX.md | `uv run extract_all_dates.py <dir>` |
| `timeline_gap_finder.py` | Compare TIMELINE.md vs DATE_INDEX.md → gap report | `uv run timeline_gap_finder.py <case_dir>` |
| `flatten_for_rag.py` | Nested dir → flat RAG dir (path encoded in filename) | `uv run flatten_for_rag.py <source_dir>` |
| `ilga_scraper.py` | Download ILCS statutes from ILGA.gov | `uv run ilga_scraper.py <chapter> <act> <section>` |
| `fetch_case_law.py` | Download Illinois appellate opinions via CourtListener | `uv run fetch_case_law.py --cite "376 Ill. App. 3d 269"` |
| `filemap.sh` | Generate FILEMAP.md with directory tree | `bash filemap.sh` (from target dir) |
| `migrate_legal_file.py` | Migrate LEGAL_FILE/ to numbered prefix structure | `uv run migrate_legal_file.py [--dry-run]` |
| `generate_response_sheet.py` | Filled PDF → two-column response sheet | `uv run generate_response_sheet.py` |
| `batch_convert_blank_forms.py` | Batch blank-form PDF → Markdown | `uv run batch_convert_blank_forms.py` |

---

## 1. Document Pipeline

### `ingest.py`
**Full ingestion pipeline.** Drop PDFs in `25FA152/INGEST/`, run this. Converts to Markdown (via `sync_legal_docs.py`), auto-classifies by content, routes to the correct LEGAL_FILE/ subdirectory, syncs RAG, regenerates FILEMAP.

```
uv run dc13_hive/scripts/ingest.py --auto --rag --filemap
uv run dc13_hive/scripts/ingest.py --file /path/to/doc.pdf --target 03_BYERS_FILINGS
uv run dc13_hive/scripts/ingest.py --report-unscanned   # → OCR_REPORT.md
uv run dc13_hive/scripts/ingest.py --track               # → UNPROCESSED.md
uv run dc13_hive/scripts/ingest.py --library-report      # → LIBRARY_AUDIT.md
```

**Flags:** `--auto` (classify), `--rag` (sync RAG), `--filemap` (regenerate FILEMAP), `--dry-run`, `--sanitize`, `--file`, `--target`, `--report-unscanned`, `--track`, `--library-report`, `--reprocess`, `--normalize`

### `sync_legal_docs.py`
**SINGLE source of truth for PDF→Markdown conversion.** No other script may contain duplicate extraction logic. Not typically invoked directly — `ingest.py` calls it as a subprocess.

### `flatten_for_rag.py`
Flatten a nested directory tree into a flat target directory. Paths are encoded into filenames (slashes → `__`). Skips `.pdf` files.

```
uv run dc13_hive/scripts/flatten_for_rag.py <source_dir> [output_dir] [--dry-run] [--cleanup]
```

### `extract_all_dates.py`
Scan all `.md`, `.txt`, `.json` files in a directory for date patterns. Produces a structured markdown date index with summary statistics.

```
uv run dc13_hive/scripts/extract_all_dates.py <directory> [--output <path>] [--min-year 2012]
```

### `timeline_gap_finder.py`
Cross-reference TIMELINE.md against DATE_INDEX.md. Reports sparse periods and unindexed dates.

```
uv run dc13_hive/scripts/timeline_gap_finder.py <case_dir>
```

---

## 2. Print / Court Submission

### `timeline_to_pdf.py`
Convert markdown legal documents into print-ready PDFs via weasyprint. Replaces the LibreOffice workflow (landscape, 0.72" margins, 13pt first paragraph).

```
uv run dc13_hive/scripts/timeline_to_pdf.py input.md [output.pdf] [options]

Options:
  --orientation {landscape,portrait}     (default: landscape)
  --margin <inches>                      (default: 0.72)
  --font-size <pt>                       (default: 12)
  --first-paragraph-size <pt>            (default: 13)
  --case-name <text>                     header left
  --case-number <text>                   header left (second line)
  --prepared-by <text>                   header right
  --no-header, --no-footer, --no-citation-manifest
```

**Examples:**
```
# Convert with defaults (landscape, 0.72" margin, first-paragraph 13pt)
uv run dc13_hive/scripts/timeline_to_pdf.py DISRUPTION_SUMMARY_GAL.md

# Portrait with custom margins and font
uv run dc13_hive/scripts/timeline_to_pdf.py my_file.md --orientation portrait --margin 0.5 --font-size 11
```

### `build_binder_pdf.py`
Combine all PDFs in a directory into a single binder PDF. Supports page numbers and an alphabetical subject index.

```
uv run dc13_hive/scripts/build_binder_pdf.py <input_dir> [output_name] [options]

Options:
  -p, --page-numbers              Add page numbers to each page
  --page-position <pos>           "bottom" (default, centered) or "side" (right edge, binding-friendly)
  -i, --index                     Add alphabetical subject index
  --index-config <json_file>      Manual index cross-references
  -o, --output <name>             Custom output name (default: COMBINED_BINDER.pdf)
```

**Examples:**
```
# Basic combine with page numbers
uv run dc13_hive/scripts/build_binder_pdf.py BINDER -p

# Full: page numbers + index with manual entries
uv run dc13_hive/scripts/build_binder_pdf.py BINDER -p -i --index-config my_index.json

# Binding-friendly: page numbers on right edge
uv run dc13_hive/scripts/build_binder_pdf.py BINDER -p --page-position side
```

**Index JSON format:**
```json
{
  "entries": [
    {"subject": "Alienation, parental", "pages": "5, 12, 31"},
    {"subject": "Discovery targets", "pages": "3, 20-25"}
  ]
}
```

The index auto-generates document-title entries from the numbered prefix PDFs in the directory, then merges any manual entries from the JSON config. Entries are sorted alphabetically, grouped by first letter, and prepended to the combined PDF.

---

## 3. Communications Pipeline

### `build_thread_master.py`
Consolidate Apple Messages, SMS HTML exports, Gmail, and Google Voice data into a single THREAD_MASTER JSON per contact.

```
uv run dc13_hive/scripts/build_thread_master.py \
    --contact <name> \
    --html-dir <sms_html_dir> \
    --gmail-dir <gmail_md_dir> \
    --gv-dir <google_voice_takeout_dir> \
    --mbox <mbox_file> \
    --existing <existing_json> \
    --output <output_json>
```

**Channel terminology:** "Apple Messages export" = iMessage + SMS-relayed from Google Voice numbers. "Google Voice account" = separate GV account (dcbyers13@gmail.com / 815-322-1013).

### `json_to_transcript.py`
Transform THREAD_MASTER JSON into a print-optimized legal transcript HTML.

```
uv run dc13_hive/scripts/json_to_transcript.py \
    -i <input.json> \
    -o <output.html> \
    [--title "Case: Byers v. Donatello"]
```

Collapses duplicates, detects tapback reactions, suppresses placeholder content, infers channel from raw sender. Output is per-sender color-coded with `page-break-inside: avoid`.

### `extract_messages.py`
Legacy script. Extracts iMessage/SMS from local SQLite `chat_backup.db`. Hardcoded paths and contact IDs.

---

## 4. Statute & Case Law Library

### `ilga_scraper.py`
Download ILCS sections from ILGA.gov as formatted Markdown.

```
# List sections in an act
uv run dc13_hive/scripts/ilga_scraper.py list 750 5

# Download a specific section
uv run dc13_hive/scripts/ilga_scraper.py 750 5 602.5 [--guiding-lights]

# Batch download from JSON config
uv run dc13_hive/scripts/ilga_scraper.py batch config.json
```

### `fetch_case_law.py`
Fetch Illinois appellate opinions from the CourtListener API and write `.md` digital twins to `CASE_LAW/`.

```
uv run dc13_hive/scripts/fetch_case_law.py --cite "376 Ill. App. 3d 269"
uv run dc13_hive/scripts/fetch_case_law.py --batch-file cases.txt
uv run dc13_hive/scripts/fetch_case_law.py --cite "376 Ill. App. 3d 269" --no-fetch   # template only
```

---

## 5. LEGAL_FILE Management

### `migrate_legal_file.py`
One-time migration tool. Copies LEGAL_FILE/ into numbered prefix structure (01_DRAFTS … 05_RELATED_CASES, 99_MISC).

```
uv run dc13_hive/scripts/migrate_legal_file.py [--dry-run]
```

### `filemap.sh`
Generate FILEMAP.md for any directory using `tree`. David's original.

```
cd <target_dir> && bash /path/to/filemap.sh
```

### `filemapper.py`
AI-generated alternative. Generate hierarchical markdown file tree.

```
python3 filemapper.py <directory> [output_file] [max_depth]
```

---

## 6. Form Processing

### `batch_convert_blank_forms.py`
Batch convert blank legal form PDFs to Markdown. Scans `blank_forms/US/` by state. Uses pdfplumber, PyMuPDF, PaddleOCR.

### `generate_response_sheet.py`
Convert a filled-out Illinois legal PDF into a printable two-column "Response Sheet" for factual rebuttal. Uses Gemini for narrative extraction.

### `form_detector.py` / `form_field_mapping.py` / `state_form_config.py`
Library modules for form type detection, field classification, and state-specific configuration. Imported by other scripts, not run directly.

---

## 7. Housekeeping

### `minify_assets.py`
Minify CSS/JS files for the Django app.

### `check_models.py`
List Google GenAI models accessible with your API key.

```
python3 check_models.py
```

---

## Archived (do not use)

### `archive/build_master_timeline.py`
**Do not run.** TIMELINE_MASTER.md is now manually edited. This script would overwrite manually validated events.
