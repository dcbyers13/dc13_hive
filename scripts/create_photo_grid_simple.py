#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Create a simple photo grid exhibit using basic PDF tools.
"""

import os
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Image, PageBreak, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from PyPDF2 import PdfMerger
import shutil

def create_photo_grid_exhibit():
    # Configuration
    photos_dir = Path("/Users/macuser/LAW_LAB/25FA152/INGEST/PHOOTOS")
    output_dir = Path("/Users/macuser/LAW_LAB/25FA152/LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND")
    print_dir = Path("/Users/macuser/LAW_LAB/25FA152/PRINT/02_EXHIBITS")
    
    # Ensure output directories exist
    output_dir.mkdir(parents=True, exist_ok=True)
    print_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect all photos in chronological order
    all_photos = []
    for year in range(2013, 2025):
        year_dir = photos_dir / str(year)
        if year_dir.exists():
            for img_file in sorted(year_dir.glob("*.PNG")):
                all_photos.append((year, img_file))
    
    print(f"Found {len(all_photos)} photos to process")
    
    if not all_photos:
        print("No photos found!")
        return None
    
    # Create grid PDF
    grid_output = output_dir / "EXHIBIT_PHOTOGRAPHIC_TIMELINE_content.pdf"
    doc = SimpleDocTemplate(str(grid_output), pagesize=letter, 
                           leftMargin=0.4*inch, rightMargin=0.4*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    styles = getSampleStyleSheet()
    
    # Custom style for captions
    caption_style = ParagraphStyle(
        'Caption',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        spaceAfter=6
    )
    
    # Header style
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=12
    )
    
    story = []
    
    # Add header to first page
    story.append(Paragraph("Case No. 25FA152 — Chronological Paternal Attachment Photolog", header_style))
    
    # Add photos in grid (2 per row, with captions)
    photos_per_row = 2
    for i, (year, img_path) in enumerate(all_photos):
        if i % photos_per_row == 0 and i > 0:
            story.append(Spacer(1, 0.2*inch))
        
        try:
            # Add image
            img = Image(str(img_path), width=3.5*inch, height=2.5*inch)
            img.hAlign = 'CENTER'
            story.append(img)
            
            # Add caption
            caption = f"[{year}] — Paternal Bonding & Shared Life Record"
            story.append(Paragraph(caption, caption_style))
            
            # Add spacing between photos
            if i % photos_per_row == 0:
                story.append(Spacer(1, 0.1*inch))
            else:
                story.append(PageBreak())
                story.append(Paragraph("Case No. 25FA152 — Chronological Paternal Attachment Photolog", header_style))
                story.append(Spacer(1, 0.1*inch))
                
        except Exception as e:
            print(f"Error processing {img_path}: {e}")
            story.append(Paragraph(f"Photo {year} — Processing Error", caption_style))
    
    # Build the document
    doc.build(story)
    print(f"Saved grid content to {grid_output}")
    
    # Create cover sheet (Exhibit W) using ReportLab
    cover_output = output_dir / "COVER_EXHIBIT_W.pdf"
    cover_doc = SimpleDocTemplate(str(cover_output), pagesize=letter,
                                  leftMargin=0.72*inch, rightMargin=0.72*inch,
                                  topMargin=0.72*inch, bottomMargin=0.72*inch)
    
    cover_story = []
    
    # Court caption styles
    court_style = ParagraphStyle('Court', parent=styles['Normal'], fontSize=12, spaceAfter=6)
    case_style = ParagraphStyle('Case', parent=styles['Normal'], fontSize=12, spaceAfter=6)
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=14, spaceAfter=8)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=12, spaceAfter=6)
    stat_style = ParagraphStyle('Stat', parent=styles['Normal'], fontSize=12, spaceAfter=12)
    
    cover_story.append(Paragraph("In the Circuit Court of the Twenty-Third Judicial Circuit, DeKalb County, Illinois.", court_style))
    cover_story.append(Paragraph("DAVID C. BYERS, Petitioner, v. PAULETTA D. DONATELLO, Respondent.", case_style))
    cover_story.append(Paragraph("Case No.: 25FA152 | Hon. Sarah Gallagher-Chami, Room 330.", case_style))
    cover_story.append(Spacer(1, 0.3*inch))
    cover_story.append(Paragraph("Exhibit W: Chronological Multi-Photo Grid Record", title_style))
    cover_story.append(Paragraph("of Long-Term Paternal Bond, Shared Household Life, and Active Caregiving (2013–2024).", subtitle_style))
    cover_story.append(Paragraph("750 ILCS 5/602.7(b)(3)", stat_style))
    
    cover_doc.build(cover_story)
    print(f"Saved cover sheet to {cover_output}")
    
    # Merge cover with grid pages
    merger = PdfMerger()
    merger.append(str(cover_output))
    merger.append(str(grid_output))
    
    final_output = output_dir / "EXHIBIT_W_PHOTOGRAPHIC_TIMELINE.pdf"
    merger.write(str(final_output))
    merger.close()
    
    # Copy to PRINT directory
    print_output = print_dir / "EXHIBIT_W_PHOTOGRAPHIC_TIMELINE.pdf"
    shutil.copy2(final_output, print_output)
    
    print(f"Final exhibit created: {final_output}")
    print(f"Copied to print directory: {print_output}")
    
    return final_output

if __name__ == "__main__":
    create_photo_grid_exhibit()
