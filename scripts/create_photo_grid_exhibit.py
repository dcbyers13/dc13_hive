#!/usr/bin/env -S uv run --script

# Copyright (C) 2026 Byers Brands, LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Create a dense multi-photo grid exhibit from sorted annual photo folders.
Generates a compact chronological collage with court-compliant cover sheet.
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap

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
    
    # Create multi-photo grid pages (4 photos per page)
    grid_pages = []
    photos_per_page = 4
    page_size = (612, 792)  # 8.5" x 11" at 72 DPI
    margin = 40
    padding = 20
    
    # Calculate photo size
    cols = 2
    photo_width = (page_size[0] - margin * 2 - padding * (cols - 1)) // cols
    photo_height = (page_size[1] - margin * 2 - padding * 3) // 2  # 2 rows
    
    for i in range(0, len(all_photos), photos_per_page):
        page_photos = all_photos[i:i + photos_per_page]
        
        # Create blank page
        page = Image.new('RGB', page_size, 'white')
        draw = ImageDraw.Draw(page)
        
        # Add header
        header_text = "Case No. 25FA152 — Chronological Paternal Attachment Photolog"
        header_font = ImageFont.load_default()
        draw.text((margin, 10), header_text, fill='black', font=header_font)
        
        # Add photos to grid
        for j, (year, img_path) in enumerate(page_photos):
            row = j // cols
            col = j % cols
            
            x = margin + col * (photo_width + padding)
            y = margin + 50 + row * (photo_height + padding + 30)  # +30 for caption
            
            try:
                # Open and resize photo
                img = Image.open(img_path)
                img.thumbnail((photo_width, photo_height), Image.Resampling.LANCZOS)
                
                # Create white background
                bg = Image.new('RGB', (photo_width, photo_height), 'white')
                bg.paste(img, ((photo_width - img.width) // 2, (photo_height - img.height) // 2))
                
                page.paste(bg, (x, y))
                
                # Add caption
                caption = f"[{year}] — Paternal Bonding & Shared Life Record"
                caption_lines = textwrap.wrap(caption, width=30)
                for k, line in enumerate(caption_lines):
                    draw.text((x, y + photo_height + 5 + k * 12), line, fill='black', font=header_font)
                    
            except Exception as e:
                print(f"Error processing {img_path}: {e}")
                # Draw placeholder
                draw.rectangle([x, y, x + photo_width, y + photo_height], outline='black')
                draw.text((x + 10, y + 10), f"Photo {year}", fill='black', font=header_font)
        
        grid_pages.append(page)
    
    # Save the grid pages
    grid_output = output_dir / "EXHIBIT_PHOTOGRAPHIC_TIMELINE_content.pdf"
    if grid_pages:
        grid_pages[0].save(
            grid_output, 
            "PDF", 
            resolution=100.0, 
            save_all=True, 
            append_images=grid_pages[1:]
        )
    
    print(f"Saved grid content to {grid_output}")
    
    # Create cover sheet (Exhibit W)
    cover = Image.new('RGB', page_size, 'white')
    draw = ImageDraw.Draw(cover)
    
    # Court caption
    court_text = "In the Circuit Court of the Twenty-Third Judicial Circuit, DeKalb County, Illinois."
    case_text = "DAVID C. BYERS, Petitioner, v. PAULETTA D. DONATELLO, Respondent."
    case_num = "Case No.: 25FA152 | Hon. Sarah Gallagher-Chami, Room 330."
    
    # Title
    exhibit_title = "Exhibit W: Chronological Multi-Photo Grid Record"
    subtitle = "of Long-Term Paternal Bond, Shared Household Life, and Active Caregiving (2013–2024)."
    statutory = "750 ILCS 5/602.7(b)(3)"
    
    # Draw court header
    try:
        title_font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 14)
    except:
        title_font = ImageFont.load_default()
        
    draw.text((margin, 50), court_text, fill='black', font=title_font)
    draw.text((margin, 70), case_text, fill='black', font=title_font)
    draw.text((margin, 90), case_num, fill='black', font=title_font)
    
    # Draw exhibit title
    try:
        bold_font = ImageFont.truetype("/Library/Fonts/Arial Bold.ttf", 16)
    except:
        bold_font = title_font
    
    draw.text((margin, 130), exhibit_title, fill='black', font=bold_font)
    draw.text((margin, 150), subtitle, fill='black', font=title_font)
    draw.text((margin, 170), statutory, fill='black', font=title_font)
    
    # Save cover sheet
    cover_output = output_dir / "COVER_EXHIBIT_W.pdf"
    cover.save(cover_output, "PDF", resolution=100.0)
    
    print(f"Saved cover sheet to {cover_output}")
    
    # Merge cover with grid pages
    from PyPDF2 import PdfMerger
    
    merger = PdfMerger()
    merger.append(cover_output)
    merger.append(grid_output)
    
    final_output = output_dir / "EXHIBIT_W_PHOTOGRAPHIC_TIMELINE.pdf"
    merger.write(final_output)
    merger.close()
    
    # Copy to PRINT directory
    print_output = print_dir / "EXHIBIT_W_PHOTOGRAPHIC_TIMELINE.pdf"
    shutil.copy2(final_output, print_output)
    
    print(f"Final exhibit created: {final_output}")
    print(f"Copied to print directory: {print_output}")
    
    return final_output

if __name__ == "__main__":
    import shutil
    create_photo_grid_exhibit()
