# Legal Case Feature: Pipeline Findings

## Overview

This document captures what the 25FA152 enrichment cycle revealed about building a
general-purpose legal case management feature for Hive. The pipeline (flatten →
extract → analyze → enrich) was run against a real 600+ document family law case.

## What Worked Well

### Date Extraction (extract_all_dates.py)
- **5-regex approach** catches most formats (ISO 8601, US M/D/Y, month-name, year-only)
- Per-year histogram is immediately useful for spotting chronological blind spots
- **False positive issue**: Numbers in serial numbers, case numbers, and OCR garbage
  produce spurious dates (e.g., `6852` as a year). Mitigation: filter out years
  outside plausible range (e.g., 1950–2030 for custody cases).

### Gap Analysis (timeline_gap_finder.py)
- Year-over-year delta (`Doc Dates - Timeline Events`) is the single most useful metric
- High-value document identification works well for spotting SMS/email sources
- **Limitation**: Many document dates are procedural (filings, docket entries) that
  should NOT be timeline events. The gap report overstates actionable gaps.
- **Improvement idea**: Add a "doc category" heuristic to distinguish procedural docs
  (court orders, docket sheets) from narrative docs (hand-prepared timelines, therapy notes).

### Timeline Enrichment
- Hand-prepared narrative timelines are the best enrichment source (90%+ yield)
- Criminal case documents contain mostly procedural dates, not narrative events
- SMS/email exports have high date density but low event signal (mostly routine
  conversation timestamps)

## What Required Manual Work

### Unicode Handling
- TIMELINE.md uses mixed Unicode apostrophes (U+2019 vs U+0027) and en-dashes
- Python scripts handle this fine; the `edit` tool requires exact matches and fails
- **Solution**: Always use Python scripts for bulk edits to TIMELINE.md

### Event Extraction from Narratives
- Converting free-form narrative paragraphs into structured 5-column table rows
  is inherently manual. LLMs could assist, but the human must validate every row.
- Each hand-prepared timeline page (PDF) yields ~7-15 events after extraction.

### Deduplication Across Sections
- Same event appears in multiple TIMELINE.md sections (e.g., battery conviction
  in both `2016–2020` and `Criminal Cases (PDD)`)
- `build_master_timeline.py` implements Jaccard similarity to deduplicate on merge
- **Threshold tuning needed**: 0.5 works but some near-duplicates slip through

## Hive Feature Recommendations

### 1. Document Ingestion Pipeline
- Implement the 4-step pipeline as Django management commands:
  `flatten_rag`, `convert_pdfs`, `extract_dates`, `gap_analysis`
- Store DATE_INDEX and GAP_ANALYSIS as database models, not markdown files
- Add a `date_extraction` model per document with confidence scores

### 2. Timeline Models
- `TimelineEvent`: date, narrative, category (FK), supporting_docs (M2M), source_file
- `Timeline`: named collection of events (e.g., "Forensic", "Legal Strategy", "Master")
- Events can belong to multiple timelines
- Partial date support: allow year-only, month-year, date ranges

### 3. Gap Analysis as a Service
- Real-time gap detection: given a timeline and document set, highlight periods
- Categorize document sources: "procedural" vs "narrative" vs "communication"
- Prioritize enrichment candidates by document type and date density

### 4. Unicode and Encoding Strategy
- Standardize on UTF-8 throughout
- Normalize smart quotes to ASCII on input, or store both with metadata
- Test all regex patterns against Unicode when deployed

### 5. RAG Integration
- Flat RAG copy (25FA152_rag/) proved essential for LLM context window limits
- Hive should maintain this mapping automatically via database foreign keys
- File renaming convention: `parentdir__childdir__filename.ext` is readable and
  reversible

## Raw Numbers (25FA152 Reference)

| Metric | Value |
|--------|-------|
| Source documents | 672 (flat RAG copy) |
| PDFs converted | 95 |
| Dates extracted | 6,852 |
| Unique doc dates | 1,059 |
| Timeline events (enriched) | 113 |
| Timeline events (master) | 97 |
| Unmatched documents | 48 |
| Largest gap | 473 days (Nov 2018 – Feb 2020) |

## Future Work

- **2019 blind spot**: 81 doc dates, 0 events — user must fill from memory or
  generate FOIA requests
- **SMS data mining**: Violette's SMS exports have 51 unmapped dates; could contain
  conversations that reveal events
- **LLM event extraction**: Test whether LLMs can reliably convert legal narrative
  paragraphs into structured timeline rows
