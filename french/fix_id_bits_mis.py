#!/usr/bin/env python3
"""
Update all CSVs in /home/amro/BUFR4-translation/french/
In the Id column, replace patterns like:
  {Num}-bits-mis-à-{xxx}  ->  All-{Num}
where Num is a number and xxx can be anything.
"""

import csv
import glob
import re
import os

FOLDER = "/home/amro/BUFR4-translation/french"
PATTERN = re.compile(r"(\d+)-bits-mis-à-\S+")

total_files = 0
total_changes = 0

for filepath in sorted(glob.glob(os.path.join(FOLDER, "*.csv"))):
    # Detect BOM
    with open(filepath, "rb") as f:
        has_bom = f.read(3) == b"\xef\xbb\xbf"

    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        continue

    header = rows[0]
    if "Id" not in header:
        continue

    id_idx = header.index("Id")
    file_changes = 0

    for row in rows[1:]:
        old_val = row[id_idx]
        new_val = PATTERN.sub(r"All-\1", old_val)
        if new_val != old_val:
            row[id_idx] = new_val
            file_changes += 1

    if file_changes > 0:
        enc = "utf-8-sig" if has_bom else "utf-8"
        with open(filepath, "w", encoding=enc, newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        total_changes += file_changes
        total_files += 1
        print(f"  {os.path.basename(filepath)}: {file_changes} change(s)")

print(f"\nDone. {total_changes} Id value(s) updated across {total_files} file(s).")
