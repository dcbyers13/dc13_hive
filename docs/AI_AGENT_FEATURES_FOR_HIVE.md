# AI Agent Capabilities for Hive

**Addendum to LEGAL_CASE_FEATURE_FINDINGS.md**

What BigPickle did manually that Hive should automate.

---

## 1. Communication Log Ingestion

### TalkingParents Parser
The full TP record is 16K lines, reverse-chronological, with inline attachments and page breaks.
- **Pattern detected**: Gaps in TP activity correlate with incarceration periods (May–Aug 2019: zero messages → David jailed)
- **Event extraction logic**: Subject lines = event candidates; message bodies = narrative detail; timestamps = exact dates
- **Hive feature**: Management command that takes a TP PDF/export, parses subject groups, extracts custody handoffs, dispute threads, and health updates as candidate `TimelineEvent` rows

### SMS/Email Mining
- Violette's SMS exports have high date density but low event signal
- **Heuristic**: Flag messages mentioning specific topics (exchange, pick up, drop off, sick, doctor, school, dance, therapy) as high-value for timeline

---

## 2. Cross-Document Event Synthesis

BigPickle combined data from 4+ document types to build coherent events:

| Document Type | Contribution |
|---|---|
| TalkingParents | Dates, narratives, disputes, health updates |
| Criminal dockets (18CF901, 14CF1932) | Sentencing dates, incarceration periods |
| School attendance | Absence patterns, health flags |
| Docket sheets (14F318) | Court events, child support, OP renewals |

**Hive feature**: When viewing a document, highlight related documents from same time period. When creating a timeline event from one source, surface related facts from other documents in a suggestion panel.

---

## 3. Gap Analysis → Action

Current gap analysis is a static report. BigPickle turned gaps into actions:
1. 2019 gap (81 doc dates, 0 events) → mined TP (Nov–Dec) + criminal docs (sentencing) → **14 events added**
2. 2023 gap (87 doc dates, 1 event) → mined TP (Mar–Jun) + 23DT666 + school → **12 events added**

**Hive feature**: Gap analysis should produce an **action plan**: "X documents from period Y have not been mapped to any event. Top candidates: [doc links]. Click to extract events."

---

## 4. Anomaly Detection

| Pattern | What It Revealed |
|---|---|
| TP silent May–Aug 2019 | David incarcerated (two sentences: 18CF901 + 14CF1932) |
| TP silent Jul–Nov 2023 | Violette's hospitalization period (Nov 2023) |
| TP jump from Jun 2023 → Dec 2024 | 18-month communication breakdown |
| "3 OPs inside 14F318" | Single umbrella case hides multiple OP cycles |

**Hive feature**: Scan communication logs for gaps >30 days; flag with opposing case events (incarceration, hospitalization, court order changes).

---

## 5. Smart Table Editing

BigPickle inserted 14 rows into TIMELINE.md maintaining exact 5-column alignment, then mirrored into TIMELINE_MASTER.md with different column structure.

**Hive feature**: Timeline tables should be database-backed (already partially done via `TimelineEvent` model), not markdown files. Markdown is for export, not storage. Frontend CRUD → DB → export to markdown.

---

## 6. File Sanitization Pipeline

`flatten_for_rag.py` now replaces spaces with underscores. But 35 existing RAG files still have spaces.

**Hive feature**: `sanitize_filenames` management command that renames files with spaces → underscores across the entire case directory, then updates all document references in the database.

---

## 7. Priority Implementation Order

| Priority | Feature | Dependencies | Effort |
|---|---|---|---|
| 1 | Communication log parser (TalkingParents) | `TimelineEvent` model exists | 2-3 days |
| 2 | Gap analysis → action plan UI | `TimelineEvent`, gap analysis service | 3-5 days |
| 3 | Anomaly detection (communication silence) | Comms parser, case model | 1-2 days |
| 4 | Cross-document correlation panel | Archive docs, vector index exists | 3-5 days |
| 5 | Markdown timeline as export, not storage | DB models exist; markdown import/export services exist | 1-2 days |
| 6 | File sanitization command | None | 0.5 day |
