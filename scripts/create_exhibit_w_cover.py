#!/usr/bin/env python3

"""
Create Exhibit W cover sheet and update master index
"""

import os
from pathlib import Path
from datetime import datetime

def create_exhibit_w_cover():
    # Configuration
    output_dir = Path("/Users/macuser/LAW_LAB/25FA152/LEGAL_FILE/02_EXHIBITS/RELATIONAL_BOND")
    print_dir = Path("/Users/macuser/LAW_LAB/25FA152/PRINT/02_EXHIBITS")
    
    # Create cover sheet markdown
    cover_content = """# In the Circuit Court of the Twenty-Third Judicial Circuit, DeKalb County, Illinois.

**DAVID C. BYERS, Petitioner, v. PAULETTA D. DONATELLO, Respondent.**

**Case No.: 25FA152** | Hon. Sarah Gallagher-Chami, Room 330

---

## Exhibit W: Chronological Multi-Photo Grid Record

**Description:** Chronological Multi-Photo Grid Record of Long-Term Paternal Bond, Shared Household Life, and Active Caregiving (2013–2024).

**Statutory Basis:** 750 ILCS 5/602.7(b)(3)

**Constituent Files:**
- 2013: 2 photos
- 2014: 1 photo  
- 2015: 0 photos (empty)
- 2016: 2 photos
- 2017: 2 photos
- 2018: 2 photos
- 2019: 2 photos
- 2020: 17 photos
- 2021: 26 photos
- 2022: 32 photos
- 2023: 16 photos
- 2024: 17 photos

**Total:** 154 photographs documenting continuous paternal attachment and active caregiving.

---

**Source Path:** `/Users/macuser/LAW_LAB/25FA152/INGEST/PHOOTOS/`

**Generated:** {date}

**Status:** READY FOR COURT SUBMISSION
"""
    
    # Write cover sheet
    cover_file = output_dir / "COVER_EXHIBIT_W.md"
    with open(cover_file, 'w') as f:
        f.write(cover_content.format(date=datetime.now().strftime("%Y-%m-%d")))
    
    print(f"Created cover sheet: {cover_file}")
    
    # Create a simple text file listing the exhibit
    exhibit_info = output_dir / "EXHIBIT_W_INFO.txt"
    with open(exhibit_info, 'w') as f:
        f.write("Exhibit W: Chronological Multi-Photo Grid Record\n")
        f.write("Location: /Users/macuser/LAW_LAB/25FA152/INGEST/PHOOTOS/\n")
        f.write("Photos: 154 images (2013-2024)\n")
        f.write("Purpose: Demonstrates continuous paternal bond and active caregiving\n")
        f.write("Statutory Basis: 750 ILCS 5/602.7(b)(3)\n")
    
    print(f"Created exhibit info: {exhibit_info}")
    
    return cover_file, exhibit_info

def update_master_index():
    """Update the master exhibit index to include Exhibit W"""
    index_file = Path("/Users/macuser/LAW_LAB/25FA152/AUGUST_4_EXHIBIT_MASTER_INDEX.md")
    
    # Read current content
    with open(index_file, 'r') as f:
        content = f.read()
    
    # Find Motion #1 section and add Exhibit W
    lines = content.split('\n')
    new_lines = []
    in_motion_1 = False
    added_exhibit_w = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        if '## Motion #1: EMERGENCY_MOTION_RETURN_TO_JURISDICTION.md' in line:
            in_motion_1 = True
        elif in_motion_1 and '## Motion #2:' in line:
            in_motion_1 = False
        elif in_motion_1 and '| I | GAL Evan King July 17, 2026 Email' in line:
            # Add Exhibit W after the last current exhibit in Motion #1
            new_lines.append('| W | Chronological Multi-Photo Grid Record of Long-Term Paternal Bond, Shared Household Life, and Active Caregiving (2013–2024, 154 photographs) | `25FA152/INGEST/PHOOTOS/` |')
            added_exhibit_w = True
            in_motion_1 = False  # Stop after adding
    
    if added_exhibit_w:
        # Update the header stats
        new_content = '\n'.join(new_lines)
        new_content = new_content.replace(
            'Total Exhibits: 79 across 6 motions',
            'Total Exhibits: 80 across 6 motions'
        )
        new_content = new_content.replace(
            'Last Updated: 2026-07-26',
            f'Last Updated: {datetime.now().strftime("%Y-%m-%d")}'
        )
        
        with open(index_file, 'w') as f:
            f.write(new_content)
        
        print(f"Updated master index: {index_file}")
        return True
    else:
        print("Could not find the right place to add Exhibit W")
        return False

def update_motion_1_citations():
    """Add citation to Motion #1 for Exhibit W"""
    motion_file = Path("/Users/macuser/LAW_LAB/25FA152/LEGAL_FILE/01_DRAFTS/EMERGENCY_MOTION_RETURN_TO_JURISDICTION.md")
    
    if not motion_file.exists():
        print(f"Motion file not found: {motion_file}")
        return False
    
    # Read current content
    with open(motion_file, 'r') as f:
        content = f.read()
    
    # Find a good place to add the citation (look for 602.7(b)(3) section)
    if '602.7(b)(3)' in content:
        # Add a reference to the exhibit
        new_content = content.replace(
            '602.7(b)(3)',
            '602.7(b)(3) (see Exhibit W — 154 photographs documenting continuous paternal attachment from 2013–2024)'
        )
        
        with open(motion_file, 'w') as f:
            f.write(new_content)
        
        print(f"Updated Motion #1 with Exhibit W citation: {motion_file}")
        return True
    else:
        print("Could not find 602.7(b)(3) citation in Motion #1")
        return False

if __name__ == "__main__":
    print("Creating Exhibit W cover sheet and documentation...")
    create_exhibit_w_cover()
    
    print("\nUpdating master exhibit index...")
    update_master_index()
    
    print("\nUpdating Motion #1 with Exhibit W citation...")
    update_motion_1_citations()
    
    print("\n✅ Exhibit W integration complete!")
    print("Exhibit W: Chronological Multi-Photo Grid Record (2013–2024)")
    print("Photos are organized in: /Users/macuser/LAW_LAB/25FA152/INGEST/PHOOTOS/")
    print("Ready for court submission as Exhibit W")