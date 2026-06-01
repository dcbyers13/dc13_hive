# Hive Application Features — Derived from Active Casework (25FA152)

**Purpose**: Permanent index of technical application features developed through iterative case-document processing. Each feature traces to a concrete workflow bottleneck identified during the Byers v. Donatello document pipeline.

---

## Feature Index

| # | Feature | Core Function | Status |
|---|---------|---------------|--------|
| 1 | **TalkingParents Parser** | Extracts raw communications into structured 5-column timeline rows (date, party, channel, summary, source doc) | Specified |
| 2 | **Gap-to-Action Pipeline** | Identifies unmonitored calendar windows from timeline gaps and prompts targeted file discovery | Specified |
| 3 | **Litigation Abuse Pattern Tracker** | Maps sequential Orders of Protection metrics to calculate cumulative access interdiction over time | Specified |
| 4 | **Anomaly Detection & Cross-Doc Validation** | Validates claims against third-party CSV/medical billing vectors (e.g., TalkingParents assertions vs. BCBS claim histories) | Specified |
| 5 | **Smart Table Inline Editor** | Permissive cell modification preserving strict data layout standards | Specified |
| 6 | **Automatic Ingestion & File Sanitization Pipeline** | Re-encodes character sets, enforces underscore formatting, routes source twins based on text keyword parsing | Deployed |
| 7 | **Auto-Gap Analysis & Remediation UI** | Surfaces coverage gaps with actionable next-steps for document recovery | Specified |
| 8 | **Narrative-to-Coordinate Extraction Engine** | Parses irregular narrative sources (police reports, FOIA exports) using regex boundary logic to isolate Incident Date, Officer ID, Agency, Charges, Arrest Status; drafts Incident Timeline Entry preview panel for one-click verification | Specified |

---

## Feature Details

### 1. TalkingParents Parser
- **Source**: TalkingParents communication logs (PDF exports)
- **Output**: Structured 5-column rows in TIMELINE.md
- **Pipeline position**: Pre-processor for timeline enrichment workflow
- **Key challenge**: Variable export formatting across date ranges

### 2. Gap-to-Action Pipeline
- **Source**: TIMELINE_GAP_ANALYSIS.md output
- **Output**: Ranked list of coverage gaps with suggested document sources
- **Pipeline position**: Post-timeline enrichment
- **Key challenge**: Distinguishing true gaps from inactive periods

### 3. Litigation Abuse Pattern Tracker
- **Source**: ORDERS_OF_PROTECTION_TIMELINE.md + docket sheets
- **Output**: Cumulative interdiction metrics (days under OP, overlap with parenting time)
- **Pipeline position**: Cross-document correlation
- **Key challenge**: Normalizing OP durations across emergency/interim/plenary phases

### 4. Anomaly Detection & Cross-Doc Validation
- **Source**: TalkingParents communications vs. medical billing (BCBS) vs. school records
- **Output**: Flagged contradictions with matched document citations
- **Pipeline position**: Post-enrichment validation
- **Key challenge**: Aligning timestamps across disparate data sources

### 5. Smart Table Inline Editor
- **Source**: TIMELINE.md, TIMELINE_MASTER.md 5-column tables
- **Output**: Permissive cell editing with structural validation
- **Pipeline position**: UI layer over timeline enrichment
- **Key challenge**: Preserving mixed Unicode while enforcing column alignment

### 6. Automatic Ingestion & File Sanitization Pipeline
- **Source**: INGEST/ drop zone → LEGAL_FILE/
- **Output**: Sanitized PDF + .md twin in numbered hierarchy, RAG copy, FILEMAP regeneration
- **Pipeline position**: Document entry point
- **Key challenge**: Auto-classification accuracy across diverse filing types
- **Status**: Deployed in `dc13_hive/scripts/ingest.py`

### 7. Auto-Gap Analysis & Remediation UI
- **Source**: timeline_gap_finder.py output
- **Output**: Curated gap report with one-click document request actions
- **Pipeline position**: Post-timeline enrichment
- **Key challenge**: Reducing false positives from intentionally inactive periods

### 8. Narrative-to-Coordinate Extraction Engine
- **Source**: Long-form police narratives, FOIA exports (e.g., South Elgin PD reports)
- **Output**: Structured Incident Timeline Entry with Incident Date, Officer ID, Reporting Agency, Charges, Arrest Status
- **Pipeline position**: Post-ingest, pre-timeline enrichment
- **Key challenge**: Variable boilerplate across law enforcement agencies; requires regex boundary logic to isolate structured data fields from narrative prose
- **Implementation target**: `core/parsers.py` within Hive app

---

## Cross-References

- Pipeline scripts: `dc13_hive/scripts/`
- Case documents: `25FA152/LEGAL_FILE/`
- Timeline artifacts: `25FA152/TIMELINE*.md`, `25FA152/LEGAL_TIMELINE.md`
- OP analysis: `25FA152/ORDERS_OF_PROTECTION_TIMELINE.md`
- Previous findings: `dc13_hive/docs/LEGAL_CASE_FEATURE_FINDINGS.md`
- AI agent roadmap: `dc13_hive/docs/AI_AGENT_FEATURES_FOR_HIVE.md`
