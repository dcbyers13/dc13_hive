#!/usr/bin/env -S uv run --script

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

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Flatten directory tree for RAG ingestion.

Copies all files from a source directory into a flat output directory,
encoding the original relative path into each filename.

Usage:
    uv run flatten_for_rag.py <source_dir> [output_dir] [--dry-run]
    uv run flatten_for_rag.py --cleanup <rag_dir> [--dry-run]

Arguments:
    source_dir   Path to the nested directory to flatten
    output_dir   Output directory (default: <source_dir>_rag)
    --dry-run    Preview what would be copied without copying
    --cleanup    Rename existing files with spaces → underscores in an existing RAG dir

Example:
    uv run flatten_for_rag.py /Users/macuser/LAW_LAB/25fa152
    uv run flatten_for_rag.py --cleanup /Users/macuser/LAW_LAB/25fa152_rag --dry-run
"""

import os
import sys
import shutil
from pathlib import Path


SKIP_DIRS = {'.git', '__pycache__', '.DS_Store', '.gitmodules'}
SKIP_FILES = {'.DS_Store'}
SEPARATOR = '__'
REPLACE_CHARS = str.maketrans({' ': '_', '\t': '_'})


def flatten(source: Path, output: Path, dry_run: bool = False) -> int:
    """
    Copy files from source to output with path-encoded filenames.

    Returns count of files copied.
    """
    seen = set()
    count = 0

    for root, dirs, files in os.walk(source):
        # Prune skip dirs in-place so os.walk doesn't descend
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        # Skip the root itself if it's .git etc.
        rel_root = Path(root).relative_to(source)
        if any(part in SKIP_DIRS for part in rel_root.parts):
            continue

        for fname in files:
            if fname in SKIP_FILES:
                continue

            src = Path(root) / fname
            rel = src.relative_to(source)

            # Build flat filename: prefix all directory parts, then the filename
            parts = list(rel.parts[:-1]) + [rel.parts[-1]]
            flat_name = SEPARATOR.join(parts)

            # Sanitize: replace spaces and tabs with underscores
            flat_name = flat_name.translate(REPLACE_CHARS)

            # De-duplicate: append (2), (3) etc. if collision
            stem, ext = os.path.splitext(flat_name)
            deduped = flat_name
            n = 2
            while deduped in seen:
                deduped = f"{stem}_{n}{ext}"
                n += 1
            seen.add(deduped)

            dest = output / deduped
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dry_run:
                print(f"  would copy: {src.relative_to(source)}")
                print(f"           →  {dest.relative_to(output)}")
            else:
                try:
                    shutil.copy2(src, dest)
                except Exception as e:
                    print(f"  error copying {src.name}: {e}", file=sys.stderr)
                    continue

            count += 1

    return count


def cleanup_rag_dir(rag_dir: Path, dry_run: bool = False) -> int:
    """
    Rename files with spaces in their names → underscores.
    Skips renamed files to avoid re-processing.

    Returns count of files renamed.
    """
    count = 0
    renamed_pairs = []  # (old_rel, new_rel)

    for root, dirs, files in os.walk(rag_dir):
        # Prune skip dirs
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in files:
            if ' ' not in fname and '\t' not in fname:
                continue

            src = Path(root) / fname
            new_name = fname.translate(REPLACE_CHARS)
            dst = src.parent / new_name

            if src == dst:
                continue

            if dst.exists():
                print(f"  skip (collision): {src.relative_to(rag_dir)}", file=sys.stderr)
                continue

            if dry_run:
                print(f"  would rename: {src.relative_to(rag_dir)}")
                print(f"            →  {dst.relative_to(rag_dir)}")
            else:
                src.rename(dst)
                print(f"  renamed: {src.relative_to(rag_dir)}")

            renamed_pairs.append((src.relative_to(rag_dir), dst.relative_to(rag_dir)))
            count += 1

    return count


def main():
    dry_run = '--dry-run' in sys.argv

    # --cleanup mode: sanitize an existing RAG directory
    if '--cleanup' in sys.argv:
        idx = sys.argv.index('--cleanup')
        if idx + 1 >= len(sys.argv):
            print("Error: --cleanup requires a RAG directory path", file=sys.stderr)
            sys.exit(1)
        rag_dir = Path(sys.argv[idx + 1]).resolve()
        if not rag_dir.is_dir():
            print(f"Error: not a directory: {rag_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Cleanup:  {rag_dir}")
        print(f"Dry run:  {dry_run}")
        print()
        count = cleanup_rag_dir(rag_dir, dry_run)
        print()
        if dry_run:
            print(f"Would rename {count} files")
        else:
            print(f"Renamed {count} files")
        return

    # Normal flatten mode
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    src = Path(sys.argv[1]).resolve()
    if not src.is_dir():
        print(f"Error: not a directory: {src}", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 2 and not sys.argv[2].startswith('--'):
        out = Path(sys.argv[2]).resolve()
    else:
        out = src.parent / f"{src.name}_rag"

    print(f"Source:   {src}")
    print(f"Output:   {out}")
    print(f"Dry run:  {dry_run}")
    print()

    count = flatten(src, out, dry_run)

    print()
    if dry_run:
        print(f"Would copy {count} files to {out}")
    else:
        print(f"Copied {count} files to {out}")


if __name__ == '__main__':
    main()
