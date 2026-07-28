#!/usr/bin/env python3
# /// script
# dependencies = ["pypdf"]
# ///

"""
Build rich, self-authenticating exhibit cover sheets for all 6 motions.

Pipeline:
  1. Parse Master Index metadata (hardcoded from AUGUST_4_EXHIBIT_MASTER_INDEX.md)
  2. Scan PRINT/02_EXHIBITS/MOTION_[X]/[LETTER]/ for underlying PDFs
  3. Generate COVER_EXHIBIT_[LETTER].md (pleading-compatible for motion_to_pdf.py)
  4. Render each to COVER_EXHIBIT_[LETTER].pdf via motion_to_pdf.py
  5. Merge cover sheet PDF + underlying PDFs → EXHIBIT_[LETTER].pdf

Usage:
    uv run dc13_hive/scripts/build_rich_cover_sheets.py [--motion N] [--dry-run]
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
from pypdf import PdfReader, PdfWriter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CASE_DIR = REPO_ROOT / "25FA152"
PRINT_DIR = CASE_DIR / "PRINT" / "02_EXHIBITS"
MOTION_TO_PDF = REPO_ROOT / "dc13_hive" / "scripts" / "motion_to_pdf.py"

PAGE_INDEX_B = """
**PAGE INDEXING NOTICE FOR COURT and GAL:**

All citations in Petitioner's pleadings formatted as (Exhibit B, ROI p. XX) correspond directly to internal page XX of the attached 134-page CenterPointe Inpatient Psychiatric Record. (Due to this 1-page Cover Sheet, internal ROI p. XX corresponds to PDF Page XX + 1 in this viewer).
"""

# ─── MOTION METADATA ───────────────────────────────────────────────────────────

MOTION_TITLES = {
    1: "Emergency Motion for Return to Jurisdiction",
    2: "Omnibus Motion to Compel Records",
    3: "Motion Addressing Parental Alienation and Endangerment",
    4: "Supplemental Petition for Rule to Show Cause",
    5: "Motion to Compel GAL Report",
    6: "Petition to Modify Allocation of Parental Responsibilities",
}

MOTION_FILENAMES = {
    1: "EMERGENCY_MOTION_RETURN_TO_JURISDICTION",
    2: "OMNIBUS_MOTION_TO_COMPEL_RECORDS",
    3: "MOTION_ADDRESS_ALIENATION_AND_ENDANGERMENT",
    4: "SUPPLEMENTAL_PETITION_RULE_TO_SHOW_CAUSE",
    5: "MOTION_TO_COMPEL_GAL_REPORT",
    6: "PETITION_TO_MODIFY",
}

# ─── EXHIBIT METADATA (from AUGUST_4_EXHIBIT_MASTER_INDEX.md) ─────────────────
# Each entry: { letter: { "description": str, "source_path": str, "category": str } }

EXHIBIT_DATA = {
    1: {
        "A": {"description": "August 3, 2022 Allocation Judgment — Sections 2 & 8 (Shared Decision-Making & Equal Records Access)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — C-SSRS Discharge Screener, Psychosocial Assessment, Discharge Care Plan, Daily Notes", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "D": {"description": "Kane County Case No. 23DT666 Criminal Conviction and Mandatory Remand Order (Sept 15–22, 2026 incarceration)", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/23DT666_DUI_CONVICTION.pdf", "category": "Legal Documents"},
        "E": {"description": "Annie Barsch, MA, LMFT Reunification Therapy Protocol and Eligibility Confirmation (Mind Matters, Elburn, IL)", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/MIND_MATTERS_PROTOCOL.pdf", "category": "Therapy Documents"},
        "F": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — documentation of ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "G": {"description": "Paternal Residential Stability Documentation (5-year lease/utility proof, Northwestern Medicine hospital records)", "source_path": "LEGAL_FILE/02_EXHIBITS/RESIDENTIAL_STABILITY/5_YEAR_LEASE_PROOF.pdf", "category": "Residential Stability"},
        "H": {"description": "Minor Child's Psychiatric History Timeline (4 hospitalizations in under 3 years: Mercy 11/2023, Streamwood 04/2026, SSM 06/2026, CenterPointe 07/2026)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/PSYCHIATRIC_HISTORY_TIMELINE.pdf", "category": "Medical Records"},
        "I": {"description": "GAL Evan King July 17, 2026 Email Refusing to Disclose Child's Hospitalization and Residential Location", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/EMAIL_2026_07_17_VIOLETTE_TREATMENT_HOUSING_CONCERNS.pdf", "category": "GAL Documents"},
        "J": {"description": "Chronological Multi-Photo Grid Record of Long-Term Paternal Bond, Shared Household Life, and Active Caregiving (2013–2024, 154 photographs)", "source_path": "LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND/EXHIBIT_J.pdf", "category": "Relational Bond / Photographic Evidence"},
    },
    2: {
        "A": {"description": "August 3, 2022 Allocation Judgment (Sections 2 & 8 — Records Access & Shared Decision-Making)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — Facesheet, Psychosocial Assessment, Discharge Care Plan, daily Psychiatry Progress Notes, Interdisciplinary Treatment Plan Updates, and Risk Assessments documenting maternal medical gatekeeping, medication obstruction, and \"constant\" suicidal ideation", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "C": {"description": "Ben Gordon Center File Closure Letter (October 27, 2025) — therapy abandoned, file closed, Respondent unreachable; perjury impeachment", "source_path": "LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_FILE_CLOSURE_LETTER_10_2025.pdf", "category": "Therapy Documents"},
        "E": {"description": "Annie Barsch, MA, LMFT Intake Protocol (Trauma-Informed Reunification Therapy)", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/MIND_MATTERS_INTAKE.pdf", "category": "Therapy Documents"},
        "F": {"description": "740 ILCS 110/4(a)(3) & 4(b) (Mental Health Records Disclosure Authority)", "source_path": "LEGAL_FILE/02_EXHIBITS/STATUTES/740_ILCS_110.pdf", "category": "Statutes"},
        "G": {"description": "Timeline of Clinical Gatekeeping (Daybreak, Streamwood, CenterPointe, Ellie, BGC)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CLINICAL_GATEKEEPING_TIMELINE.pdf", "category": "Medical Records"},
        "H": {"description": "Ben Gordon Center March 11, 2025 IATP (Court-Ordered Individual Therapy Mandate)", "source_path": "LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_IATP_2025.pdf", "category": "Therapy Documents"},
        "I": {"description": "NW Medicine Psychiatry Intake Note (March 11, 2025) — \"Counselor or Therapist: No\"; placement history incl. homelessness", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/NW_MEDICINE_INTAKE_EXCERPT_2025.pdf", "category": "Medical Records"},
        "J": {"description": "BGC Group Session Clinical Log — 18 visits March–October 2025 (post-IATP treatment compliance)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/BGC_17_GROUP_SESSIONS_CLINICAL_LOG.pdf", "category": "Medical Records"},
        "K": {"description": "Daybreak Health Records Request Thread (May 7–11, 2026) — statutory demand under 750 ILCS 5/602.11 for tele-therapy records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/DAYBREAK_HEALTH_RECORDS_REQUEST_THREAD_05_2026.pdf", "category": "Medical Records"},
        "L": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "M": {"description": "Ellie Mental Health Records Request (July 24, 2026) — ROI submission for treatment date details", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/ELLIE_MENTAL_HEALTH_ROI_REQUEST_07_2026.pdf", "category": "Medical Records"},
        "N": {"description": "TalkingParents Subscription Inactivity Proof — platform screenshots documenting Respondent's deliberate abandonment of court-ordered communication channels", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/TALKINGPARENTS_SUBSCRIPTION_PROOF.pdf", "category": "Communication"},
        "O": {"description": "GAL Evan King July 17, 2026 Email Refusing to Disclose Child's Hospitalization and Location", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/EMAIL_2026_07_17_VIOLETTE_TREATMENT_HOUSING_CONCERNS.pdf", "category": "GAL Documents"},
    },
    3: {
        "A": {"description": "August 3, 2022 Allocation Judgment (Shared Decision-Making & Parenting Time)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — Facesheet, Psychosocial Assessment, Discharge Care Plan, daily Psychiatry Progress Notes, Interdisciplinary Treatment Plan Updates, and Risk Assessments documenting maternal incapacity admission, medication obstruction, \"constant\" suicidal ideation with overdose plan, and Farmington MO living environment", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "C": {"description": "Ben Gordon Center File Closure Letter (October 27, 2025) — abandonment of doctor-ordered therapy, perjury impeachment", "source_path": "LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_FILE_CLOSURE_LETTER_10_2025.pdf", "category": "Therapy Documents"},
        "D": {"description": "Kane County Case No. 23DT666 Criminal Conviction & Remand Order", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/23DT666_DUI_CONVICTION.pdf", "category": "Legal Documents"},
        "E": {"description": "Annie Barsch, MA, LMFT Reunification Therapy Protocol & GAL Notice", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/MIND_MATTERS_PROTOCOL.pdf", "category": "Therapy Documents"},
        "F": {"description": "24OP613 Order of Protection Filing & Voluntary Withdrawal (Fabricated Claims)", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/24OP613_WITHDRAWAL.pdf", "category": "Legal Documents"},
        "G": {"description": "Timeline of 20-Month Alienation Campaign (Dec 2024 – Jul 2026)", "source_path": "LEGAL_FILE/02_EXHIBITS/ALIENATION/20_MONTH_ALIENATION_TIMELINE.pdf", "category": "Alienation"},
        "H": {"description": "Clinical Records Timeline (4 Hospitalizations, 32-Month Care Vacuum)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CLINICAL_GATEKEEPING_TIMELINE.pdf", "category": "Medical Records"},
        "I": {"description": "In re Marriage of Bates, 212 Ill. 2d 489 (2004) (Illinois Supreme Court Controlling Precedent on Parental Alienating Conduct & Best Interests)", "source_path": "LEGAL_FILE/02_EXHIBITS/CASE_LAW/BATES_CASE.pdf", "category": "Case Law"},
        "J": {"description": "GAL Reunification Counseling Thread (March 3–18, 2026) — court-ordered reunification counseling per Jan 22 Order; maternal non-responsiveness", "source_path": "LEGAL_FILE/COMMS/2026_03_03_GAL_REUNIFICATION_COUNSELING_THREAD.pdf", "category": "Communication"},
        "K": {"description": "Ryan & Ryan Historical Narrative Thread (October 25, 2021) — 2018 ER pneumonia incident, medical neglect pattern", "source_path": "LEGAL_FILE/COMMS/2021_10_25_RYAN_AND_RYAN_REEVALUATION_THREAD.pdf", "category": "Communication"},
        "L": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "M": {"description": "John Schroeder Weapons Arrest Record (21CF1065)", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/21CF1065_WEAPONS_RECORD.pdf", "category": "Legal Documents"},
        "N": {"description": "Certified TalkingParents Excerpt (Mar 2026, pp. 12–16) & Petitioner's Multi-Provider Reunification Search Log (Jan 11, 2026, pp. 6–8) — Extrajudicial lockout admissions and therapeutic gatekeeping", "source_path": "PRINT/02_EXHIBITS/MOTION_3/N/EXHIBIT_N.pdf", "category": "Communication"},
        "O": {"description": "GAL Evan King July 17–27, 2026 Complete Email Thread Refusing to Disclose Child's Hospitalization and Location", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/2026_07_27_VIOLETTE_GMAIL.pdf", "category": "GAL Documents"},
        "P": {"description": "Chronological Photographic Ledger of Paternal Caregiving and Shared Co-Residence (2013–2024) — Objective visual documentation directly refuting Respondent's litigation-driven narrative of paternal disconnection", "source_path": "LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND/EXHIBIT_J.pdf", "category": "Relational Bond / Photographic Evidence"},
    },
    4: {
        "A": {"description": "August 3, 2022 Allocation Judgment (Sections 2, 8, and 21)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — Facesheet, Psychosocial Assessment, Discharge Care Plan, daily Psychiatry Progress Notes, Interdisciplinary Treatment Plan Updates, and Risk Assessments documenting maternal incapacity admission, medication obstruction, \"constant\" suicidal ideation with overdose plan, and Farmington MO living environment", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "F": {"description": "Proof of Unauthorized Missouri Relocation (June 15, 2026)", "source_path": "LEGAL_FILE/02_EXHIBITS/RELOCATION/EVIDENCE_MO_RELOCATION.pdf", "category": "Relocation Evidence"},
        "G": {"description": "Streamwood Behavioral Healthcare System Records (April 10–22, 2026)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/STREAMWOOD_HOSPITAL_04_2026.pdf", "category": "Medical Records"},
        "H": {"description": "Timeline of 20-Month Parenting Time Deprivation (December 2024 – Present) — including 8 police reports", "source_path": "LEGAL_FILE/02_EXHIBITS/PARENTING_TIME/20_MONTH_DEPRIVATION_TIMELINE.pdf", "category": "Parenting Time"},
        "I": {"description": "GAL Evan King's July 17, 2026 Email Confirming Concealment Pattern and Refusal to Disclose", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/EMAIL_2026_07_17_VIOLETTE_TREATMENT_HOUSING_CONCERNS.pdf", "category": "GAL Documents"},
        "J": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "K": {"description": "TalkingParents Subscription Inactivity Proof — platform screenshots documenting Respondent's deliberate abandonment of court-ordered communication channels", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/TALKINGPARENTS_SUBSCRIPTION_PROOF.pdf", "category": "Communication"},
        "N": {"description": "Certified TalkingParents Excerpt (Mar 2026, pp. 12–16) & Petitioner's Multi-Provider Reunification Search Log (Jan 11, 2026, pp. 6–8) — Extrajudicial lockout admissions and therapeutic gatekeeping", "source_path": "PRINT/02_EXHIBITS/MOTION_4/N/EXHIBIT_N.pdf", "category": "Communication"},
    },
    5: {
        "A": {"description": "August 3, 2022 Allocation Judgment (Sections 2 & 8 — Shared Decision-Making & Parenting Time)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — Facesheet, Psychosocial Assessment, Discharge Care Plan, daily Psychiatry Progress Notes, Interdisciplinary Treatment Plan Updates, and Risk Assessments documenting maternal incapacity admission, medication obstruction, \"constant\" suicidal ideation with overdose plan, and Farmington MO living environment", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "F": {"description": "January 22, 2026 Order Appointing GAL Evan King", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/GAL_APPOINTMENT_2026.pdf", "category": "Court Orders"},
        "G": {"description": "May 4, 2026 Written Demand for Local Home Visits", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/DEMAND_LETTER_05_04_2026.pdf", "category": "GAL Documents"},
        "H": {"description": "July 2, 2026 Email from Petitioner to GAL Evan King Demanding Investigation of Minor Child's Post-Relocation Housing, Cohabitants, and School Enrollment Status", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/GAL_EMAIL_HOUSING_SITUATION_JUL_2_2026.pdf", "category": "GAL Documents"},
        "I": {"description": "June 7, 2026 Email from Petitioner to Annie Barsch, MA, LMFT Re: Waitlist and Reunification Therapy Intake Protocol, CC'd to GAL Evan King", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/RE_WAITLIST_JUN_7_2026.pdf", "category": "GAL Documents"},
        "J": {"description": "June 29, 2026 Follow-up from Petitioner to Annie Barsch CC'd to GAL Evan King re: Reunification Therapy Scheduling", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/RE_WAITLIST_JUN_29_2026.pdf", "category": "GAL Documents"},
        "K": {"description": "July 17, 2026 GAL Email Confirming CenterPointe Hospitalization and Refusing to Disclose", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/EMAIL_2026_07_17_VIOLETTE_TREATMENT_HOUSING_CONCERNS.pdf", "category": "GAL Documents"},
        "L": {"description": "Timeline of GAL Inaction (January 22, 2026 – Present)", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/GAL_INACTION_TIMELINE.pdf", "category": "GAL Documents"},
        "M": {"description": "750 ILCS 5/506 (Guardian ad Litem Duties and Reporting)", "source_path": "LEGAL_FILE/02_EXHIBITS/STATUTES/750_ILCS_506.pdf", "category": "Statutes"},
        "N": {"description": "GAL Reunification Counseling Thread (March 3, 2026) — court-ordered reunification counseling per Jan 22 Order; maternal non-responsiveness", "source_path": "LEGAL_FILE/COMMS/2026_03_03_GAL_REUNIFICATION_COUNSELING_THREAD.pdf", "category": "Communication"},
        "O": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "P": {"description": "June 16, 2026 Transmittal Email to GAL Evan King — proactive disclosure of comprehensive case file", "source_path": "LEGAL_FILE/02_EXHIBITS/COMBINED_BINDER.pdf", "category": "GAL Documents"},
        "Q": {"description": "Chronological Photographic Ledger of Paternal Caregiving and Shared Co-Residence (2013–2024) — provided to GAL Evan King as material evidence to evaluate the historical attachment bond under 750 ILCS 5/506", "source_path": "LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND/EXHIBIT_J.pdf", "category": "Relational Bond / Photographic Evidence"},
    },
    6: {
        "A": {"description": "August 3, 2022 Allocation Judgment (Kane County Case No. 14F318)", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/ALLOCATION_JUDGMENT_2022.pdf", "category": "Court Orders"},
        "B": {"description": "CenterPointe Hospital of Columbia, MO Inpatient Psychiatric Records (ROI, July 8–23, 2026, 134 pages) — Facesheet, Psychosocial Assessment, Discharge Care Plan, daily Psychiatry Progress Notes, Interdisciplinary Treatment Plan Updates, and Risk Assessments documenting maternal incapacity admission, medication obstruction, \"constant\" suicidal ideation with overdose plan, and Farmington MO living environment", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_RECORDS_07_2026.pdf", "category": "Medical Records"},
        "C": {"description": "Ben Gordon Center File Closure Letter (October 27, 2025) — abandonment of doctor-ordered therapy, perjury impeachment", "source_path": "LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_FILE_CLOSURE_LETTER_10_2025.pdf", "category": "Therapy Documents"},
        "D": {"description": "Kane County Case No. 23DT666 Criminal Conviction and Mandatory Remand Order (June 10, 2026) — DUI guilty plea, 24-month Conditional Discharge, mandatory incarceration September 15–22, 2026", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/23DT666_DUI_CONVICTION.pdf", "category": "Legal Documents"},
        "E": {"description": "Mind Matters Reunification Therapy Protocol (Annie Barsch, MA, LMFT) — 3-step trauma-informed intake, age eligibility confirmed July 16, 2026", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/MIND_MATTERS_PROTOCOL.pdf", "category": "Therapy Documents"},
        "F": {"description": "Motion for Nunc Pro Tunc Order (filed May 19, 2026) with supporting evidence", "source_path": "LEGAL_FILE/02_EXHIBITS/COURT_ORDERS/NUNC_PRO_TUNC_MOTION.pdf", "category": "Court Orders"},
        "G": {"description": "Order Terminating OP (February 7, 2025) — Voluntary withdrawal of 24OP613", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/24OP613_TERMINATION.pdf", "category": "Legal Documents"},
        "H": {"description": "Guardianship Agreement (June 2024) granting Petitioner care of Zadyn Neill", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/GUARDIANSHIP_AGREEMENT_2024.pdf", "category": "Legal Documents"},
        "I": {"description": "Mercy Medical Record (March 2025) — Respondent's admission of homelessness", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/MERCY_MEDICAL_2025.pdf", "category": "Medical Records"},
        "J": {"description": "Police Complaints (April 2025 – October 2025) — 8 complaints for Unlawful Visitation Interference", "source_path": "LEGAL_FILE/02_EXHIBITS/POLICE_REPORTS/COMPLAINTS_2025.pdf", "category": "Police Reports"},
        "K": {"description": "Amended OP Petition (April 10, 2026) — Case No. 26OP618", "source_path": "LEGAL_FILE/02_EXHIBITS/LEGAL_DOCUMENTS/26OP618_AMENDED_PETITION.pdf", "category": "Legal Documents"},
        "L": {"description": "Forensic Communication Analysis — Minor child's text message patterns", "source_path": "LEGAL_FILE/01_DRAFTS/8_FORENSIC-ANALYSIS-VIOLETTE-COMMS.pdf", "category": "Forensic Analysis"},
        "M": {"description": "BCBS Claims Summary — Zero individual therapy sessions over 2.5 years", "source_path": "LEGAL_FILE/02_EXHIBITS/INSURANCE/BCBS_CLAIMS_SUMMARY.pdf", "category": "Insurance"},
        "N": {"description": "Certified TalkingParents Excerpt (Mar 2026, pp. 12–16) & Petitioner's Multi-Provider Reunification Therapists Survey (Jan 11, 2026, pp. 6–8) — Extrajudicial lockout admissions, therapeutic gatekeeping, and GAL notice of Respondent's self-admitted lockout", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/TALKINGPARENTS_RECORD.pdf", "category": "Communication"},
        "O": {"description": "Violette Apology Letter (April 8, 2025) — handwritten letter evidencing parental bond, non-abandonment, emotional devotion", "source_path": "LEGAL_FILE/02_EXHIBITS/PARENTING_TIME/VIOLETTE_APOLOGY_LETTER.pdf", "category": "Parenting Time"},
        "P": {"description": "CenterPointe Hospital ROI Email Thread (July 20–23, 2026) — ROI execution for MO inpatient records", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/CENTERPOINTE_ROI_EMAIL_THREAD_07_2026.pdf", "category": "Medical Records"},
        "Q": {"description": "Ryan & Ryan Historical Narrative Thread (October 25, 2021) — 2018 ER pneumonia incident, medical neglect pattern", "source_path": "LEGAL_FILE/COMMS/2021_10_25_RYAN_AND_RYAN_REEVALUATION_THREAD.pdf", "category": "Communication"},
        "R": {"description": "17CM2499 (September 2, 2017) — Respondent's battery conviction against minor child", "source_path": "LEGAL_FILE/02_EXHIBITS/POLICE_REPORTS/17CM2499_BATTERY_CONVICTION.pdf", "category": "Police Reports"},
        "S": {"description": "Streamwood Behavioral Healthcare System Records (April 10–22, 2026)", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/STREAMWOOD_HOSPITAL_04_2026.pdf", "category": "Medical Records"},
        "T": {"description": "Ben Gordon Center March 11, 2025 IATP (Court-Ordered Individual Therapy Mandate)", "source_path": "LEGAL_FILE/02_EXHIBITS/THERAPY_DOCS/BGC_IATP_2025.pdf", "category": "Therapy Documents"},
        "U": {"description": "GAL Evan King July 17–27, 2026 Complete Email Thread Refusing to Disclose Child's Hospitalization, Location, and Post-Discharge Placement", "source_path": "LEGAL_FILE/02_EXHIBITS/GAL_DOCS/2026_07_27_VIOLETTE_GMAIL.pdf", "category": "GAL Documents"},
        "V": {"description": "NW Medicine Psychiatry Intake Note (March 11, 2025) — \"Counselor or Therapist: No\"; placement history incl. homelessness", "source_path": "LEGAL_FILE/02_EXHIBITS/MEDICAL_RECORDS/NW_MEDICINE_INTAKE_EXCERPT_2025.pdf", "category": "Medical Records"},
        "W": {"description": "TalkingParents Subscription Inactivity Proof — platform screenshots demonstrating Respondent's deliberate abandonment of court-ordered communication channels", "source_path": "LEGAL_FILE/02_EXHIBITS/COMMUNICATION/TALKINGPARENTS_SUBSCRIPTION_PROOF.pdf", "category": "Communication"},
        "X": {"description": "Chronological Photographic Ledger of Paternal Caregiving and Shared Co-Residence (2013–2024) — Objective visual documentation establishing an 11-year history of continuous parental involvement, shared household life, and primary caregiving prior to the December 2024 extrajudicial lockout, including the November 6, 2023 Mercy Medical discharge pickup (IMG_5241), directly supporting the statutory best-interests analysis under 750 ILCS 5/602.7(b)(1)", "source_path": "LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND/EXHIBIT_J.pdf", "category": "Relational Bond / Photographic Evidence"},
    },
}

# ─── CONFIDENTIAL STAMP MAPPING (per-motion) ──────────────────────────────────
# Only exhibits listed here get the red CONFIDENTIAL rubber stamp on their cover sheet.

CONFIDENTIAL_EXHIBITS = {
    1: {"B", "H", "I"},
    2: {"B", "C", "G", "H", "I", "J", "O"},
    3: {"B", "C", "H", "N", "O"},
    4: {"B", "G", "I", "N"},
    5: {"B", "G", "K"},
    6: {"B", "C", "F", "I", "L", "M", "N", "S", "T", "U"},
}

def is_confidential(motion_num, exhibit_letter):
    return exhibit_letter.upper() in CONFIDENTIAL_EXHIBITS.get(int(motion_num), set())


def scan_exhibit_pdfs(exhibit_dir: Path, motion_num: int = 0) -> list[str]:
    """Scan directory for underlying PDFs, excluding cover sheets and merged outputs."""
    pdfs = []
    if not exhibit_dir.exists():
        return pdfs
    
    # Manual order for Exhibit E (Mind Matters)
    if exhibit_dir.name == "E":
        manual_order = [
            "THERAPIST_EMAIL_WAITLIST_JUN_5-7_2026.pdf",
            "THERAPIST_EMAIL_WAITLIST_FOLLOWUP_JUN_7-JUL_1_2026.pdf",
            "MIND_MATTERS_PROTOCOL.pdf"
        ]
        for fname in manual_order:
            f = exhibit_dir / fname
            if f.exists():
                pdfs.append(f.name)
        # Add any other files that aren't in our manual order
        for f in sorted(exhibit_dir.iterdir()):
            if f.suffix.lower() == ".pdf" and not f.name.startswith(("EXHIBIT_", "COVER_")) and f.name not in pdfs:
                pdfs.append(f.name)
        return pdfs
    
    # Manual order for Exhibit N (TalkingParents Excerpt + Reunification Search Log)
    if exhibit_dir.name == "N" and motion_num in (3, 4, 5):
        manual_order = [
            "TALKINGPARENTS_EXCERPT_PP12-16.pdf",
            "REUNIFICATION_THERAPISTS_SUMMARY.pdf"
        ]
        for fname in manual_order:
            f = exhibit_dir / fname
            if f.exists():
                pdfs.append(f.name)
        # Add any other files that aren't in our manual order
        for f in sorted(exhibit_dir.iterdir()):
            if f.suffix.lower() == ".pdf" and not f.name.startswith(("EXHIBIT_", "COVER_")) and f.name not in pdfs:
                pdfs.append(f.name)
        return pdfs
    
    # Manual order for Exhibit N (Motion 6 — TalkingParents Thread + Reunification Therapists Survey)
    if exhibit_dir.name == "N" and motion_num == 6:
        manual_order = [
            "TALKINGPARENTS_REUNIFICATION_THERAPY_THREAD.pdf",
            "REUNIFICATION_THERAPISTS_SURVEY.pdf"
        ]
        for fname in manual_order:
            f = exhibit_dir / fname
            if f.exists():
                pdfs.append(f.name)
        # Add any other files that aren't in our manual order
        for f in sorted(exhibit_dir.iterdir()):
            if f.suffix.lower() == ".pdf" and not f.name.startswith(("EXHIBIT_", "COVER_")) and f.name not in pdfs:
                pdfs.append(f.name)
        return pdfs
    
    # Default alphabetical order for other exhibits
    for f in sorted(exhibit_dir.iterdir()):
        if f.suffix.lower() == ".pdf" and not f.name.startswith(("EXHIBIT_", "COVER_")):
            pdfs.append(f.name)
    return pdfs


def get_page_count(pdf_path: Path) -> int:
    """Get page count of a PDF file."""
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception:
        return 0


def generate_cover_sheet_md(letter: str, motion_num: int, exhibit_info: dict, pdf_filenames: list[str]) -> str:
    """Generate pleading-compatible markdown cover sheet for an exhibit."""
    motion_title = MOTION_TITLES[motion_num]
    description = exhibit_info["description"]
    source_path = exhibit_info["source_path"]
    category = exhibit_info["category"]
    source_filename = Path(source_path).name
    confidential = is_confidential(motion_num, letter)

    # Build the sub-index of constituent files
    sub_index_lines = []
    if len(pdf_filenames) == 1:
        sub_index_lines.append(f"1. `{pdf_filenames[0]}`")
    else:
        for i, fname in enumerate(pdf_filenames, 1):
            # Extract complaint number from filename if it's a police report
            sub_index_lines.append(f"{i}. `{fname}`")

    sub_index = "\n\n".join(sub_index_lines)

    # Build source file listing
    if len(pdf_filenames) == 1:
        source_listing = f"  - `{source_filename}`"
    else:
        source_listing = "\n".join(f"  - `{f}`" for f in pdf_filenames)

    # Escape double quotes in description for markdown
    description_escaped = description.replace('"', '\\"')

    # Confidential stamp — absolutely positioned in right margin
    confidential_div = ""
    if confidential:
        confidential_div = '\n<div style="position: absolute; top: 2.2in; right: 0.5in; border: 3px solid #cc0000; color: #cc0000; font-weight: bold; font-size: 14pt; padding: 4px 10px; transform: rotate(-4deg); letter-spacing: 2px;">CONFIDENTIAL</div>\n'

    md = f"""**IN THE CIRCUIT COURT OF THE TWENTY-THIRD JUDICIAL CIRCUIT DEKALB COUNTY, ILLINOIS**

**DAVID C. BYERS**, Petitioner,

vs.

**PAULETTA D. DONATELLO**, Respondent.

**Case No. 25FA152 — Honorable Sarah Gallagher-Chami, Room 330**
{confidential_div}
---

<div style="font-size: 22pt; font-weight: bold; margin-top: 24pt; margin-bottom: 12pt;">EXHIBIT {letter}</div>

**FILED IN SUPPORT OF:** {motion_title}

---

### DOCUMENT SUMMARY

**Description:**
{description}
{PAGE_INDEX_B if letter == "B" else ""}
**Constituent File Sub-Index:**

{sub_index}

---

**PRIMARY EVIDENCE CATEGORY:** {category}

---

*This exhibit cover sheet is attached as Page 1 to certify and authenticate the underlying document(s) submitted into the record for Case No. 25FA152.*"""
    return md


def render_cover_sheet_pdf(md_path: Path, pdf_path: Path) -> bool:
    """Render cover sheet markdown to PDF using motion_to_pdf.py via uv run."""
    cmd = [
        "uv", "run", str(MOTION_TO_PDF),
        str(md_path), str(pdf_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"    [ERROR] motion_to_pdf.py failed: {result.stderr.strip()}")
        return False
    return True


def merge_pdfs(cover_pdf: Path, exhibit_pdfs: list[Path], output_pdf: Path) -> bool:
    """Merge cover sheet PDF (page 1) with underlying exhibit PDFs."""
    writer = PdfWriter()

    # Add cover sheet as page 1
    try:
        cover_reader = PdfReader(str(cover_pdf))
        for page in cover_reader.pages:
            writer.add_page(page)
    except Exception as e:
        print(f"    [ERROR] Failed to read cover PDF: {e}")
        return False

    # Add all underlying exhibit PDFs in order
    for pdf_path in exhibit_pdfs:
        try:
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                writer.add_page(page)
        except Exception as e:
            print(f"    [WARNING] Failed to read {pdf_path.name}: {e}")

    # Write merged output
    try:
        with open(output_pdf, "wb") as f:
            writer.write(f)
        return True
    except Exception as e:
        print(f"    [ERROR] Failed to write merged PDF: {e}")
        return False


def process_exhibit(motion_num: int, letter: str, dry_run: bool = False) -> dict:
    """Process a single exhibit: generate cover, render PDF, merge."""
    exhibit_dir = PRINT_DIR / f"MOTION_{motion_num}" / letter
    exhibit_info = EXHIBIT_DATA[motion_num].get(letter)

    if not exhibit_info:
        return {"status": "skipped", "reason": "no metadata"}

    # Scan for underlying PDFs
    pdf_filenames = scan_exhibit_pdfs(exhibit_dir, motion_num)
    if not pdf_filenames:
        return {"status": "skipped", "reason": "no PDFs found"}

    # Paths
    md_path = exhibit_dir / f"COVER_EXHIBIT_{letter}.md"
    cover_pdf_path = exhibit_dir / f"COVER_EXHIBIT_{letter}.pdf"
    final_pdf_path = exhibit_dir / f"EXHIBIT_{letter}.pdf"

    # Generate cover sheet markdown
    md_content = generate_cover_sheet_md(letter, motion_num, exhibit_info, pdf_filenames)

    if dry_run:
        print(f"  [DRY-RUN] Would generate {md_path.name}")
        return {"status": "dry-run", "pages": 0}

    # Write markdown
    md_path.write_text(md_content, encoding="utf-8")

    # Render to PDF
    if not render_cover_sheet_pdf(md_path, cover_pdf_path):
        return {"status": "error", "reason": "PDF render failed"}

    # Get cover sheet page count
    cover_pages = get_page_count(cover_pdf_path)

    # Build list of underlying PDFs (full paths)
    underlying_pdfs = [exhibit_dir / f for f in pdf_filenames]

    # Merge
    if not merge_pdfs(cover_pdf_path, underlying_pdfs, final_pdf_path):
        return {"status": "error", "reason": "merge failed"}

    # Get final page count
    final_pages = get_page_count(final_pdf_path)

    return {
        "status": "success",
        "cover_pages": cover_pages,
        "total_pages": final_pages,
        "underlying_files": len(pdf_filenames),
        "md_path": str(md_path),
        "final_pdf": str(final_pdf_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Build rich exhibit cover sheets with metadata")
    parser.add_argument("--motion", type=int, help="Process only this motion number (1-6)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    motions = [args.motion] if args.motion else [1, 2, 3, 4, 5, 6]

    total_generated = 0
    total_compiled = 0
    total_merged = 0
    total_errors = 0
    results = {}

    for motion_num in motions:
        exhibits = EXHIBIT_DATA.get(motion_num, {})
        if not exhibits:
            print(f"\n[SKIP] Motion #{motion_num}: no exhibit data")
            continue

        print(f"\n{'='*60}")
        print(f"  MOTION #{motion_num}: {MOTION_TITLES[motion_num]}")
        print(f"  Exhibits: {', '.join(sorted(exhibits.keys()))}")
        print(f"{'='*60}")

        for letter in sorted(exhibits.keys()):
            print(f"\n  [{letter}] Processing...", end=" ")
            result = process_exhibit(motion_num, letter, dry_run=args.dry_run)
            results[f"M{motion_num}_{letter}"] = result

            if result["status"] == "success":
                total_generated += 1
                total_compiled += 1
                total_merged += 1
                print(f"OK  cover={result['cover_pages']}p  total={result['total_pages']}p  ({result['underlying_files']} files)")
            elif result["status"] == "dry-run":
                total_generated += 1
                print(f"DRY-RUN")
            elif result["status"] == "skipped":
                print(f"SKIP ({result['reason']})")
            else:
                total_errors += 1
                print(f"ERROR ({result['reason']})")

    # Summary
    print(f"\n{'='*60}")
    print(f"  EXECUTION SUMMARY")
    print(f"{'='*60}")
    print(f"  Cover sheets generated:  {total_generated}")
    print(f"  Compiled to PDF:         {total_compiled}")
    print(f"  Merged into finals:      {total_merged}")
    print(f"  Errors:                  {total_errors}")
    print(f"{'='*60}")

    # Write manifest
    manifest_path = PRINT_DIR / "COVER_SHEET_MANIFEST.json"
    manifest = {
        "total_generated": total_generated,
        "total_compiled": total_compiled,
        "total_merged": total_merged,
        "total_errors": total_errors,
        "results": results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n  Manifest written to: {manifest_path}")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
