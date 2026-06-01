#!/bin/bash
# filemap.sh — generates FILEMAP.md for the whole LAW_LAB repo
# Run from anywhere: bash /path/to/filemap.sh
# Outputs to current directory as FILEMAP.md

MAP_NAME="FILEMAP.md"
HERE=$(cd "$(dirname "$0")/../.." && pwd)  # root of LAW_LAB

{
    echo "# File Map: LAW_LAB"
    echo "Generated: $(date)"
    echo ""

    # ── Top-level skeleton ──
    echo "## Top Level"
    echo ""
    echo '```'
    tree -F --dirsfirst -L 2 "$HERE" -I '25fa152_rag' | head -200
    echo '```'
    echo ""

    # ── GUIDING_LIGHTS ──
    echo "## GUIDING_LIGHTS/ — Key Case Documents"
    echo ""
    echo '```'
    ls -1 "$HERE/GUIDING_LIGHTS"
    echo '```'
    echo ""

    # ── LAW_LIBRARY ──
    echo "## LAW_LIBRARY/ — Illinois Compiled Statutes (50 files)"
    echo ""
    echo '```'
    ls -1 "$HERE/LAW_LIBRARY"
    echo '```'
    echo ""

    # ── 25fa152/ case documents ──
    echo "## 25fa152/ — Case Document Library"
    echo ""
    echo '```'
    tree -F --dirsfirst -L 3 "$HERE/25fa152" -I 'AGENTS.md|FILEMAP.md|LEGAL_FILE/COMMS|LEGAL_FILE/MEDICAL_MENTAL|LEGAL_FILE/SCHOOL|LEGAL_FILE/LEGAL_FILE|LEGAL_FILE/0_DRAFTS|LEGAL_FILE/ACTIVE_ORDERS' | head -300
    echo '```'
    echo ""
    echo "### LEGAL_FILE/ subdirectories"
    echo ""
    echo '```'
    tree -F --dirsfirst -L 2 "$HERE/25fa152/LEGAL_FILE"
    echo '```'
    echo ""

    # ── dc13_hive/ ──
    echo "## dc13_hive/ — Django App & Scripts"
    echo ""
    echo '```'
    tree -F --dirsfirst -L 3 "$HERE/dc13_hive" -I '__pycache__'
    echo '```'
    echo ""

    # ── 25fa152_rag/ summary ──
    RAG_COUNT=$(find "$HERE/25fa152_rag" -type f | wc -l)
    echo "## 25fa152_rag/ — Flat RAG Copy ($RAG_COUNT files)"
    echo ""
    echo '```'
    tree -F --dirsfirst -L 1 "$HERE/25fa152_rag" | head -40
    echo "├── ... ($RAG_COUNT files total — PDF + MD pairs from all case subdirs)"
    echo '```'
    echo ""
    echo "Filenames encode original paths, e.g.:"
    echo '- `LEGAL_FILE_FILED_MOTIONS_EXHIBITS_ETC_2025_10_27-MOTION_TO_COMPEL_MEDIATION.pdf`'
    echo '- `COMMS_TALKINGPARENTS_RECORD_COMPLETE-4_2_2026.md`'
    echo ""

} > "$MAP_NAME"

echo "Wrote $MAP_NAME ($(wc -l < "$MAP_NAME") lines)"
