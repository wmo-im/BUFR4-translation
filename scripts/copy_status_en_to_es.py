#!/usr/bin/env python3
from pathlib import Path
import csv

# Search roots: repository and external draft folder
ROOTS = [Path.cwd()]
extra = Path(r"c:\Users\WMO work\WMO\Governance Services - Language Jobs - 5. 306_v.I.2_2025 edition\Draft for AI translation\ai-translation-first-files-for-review")
if extra.exists():
    ROOTS.append(extra)

def find_en_file(en_name):
    for root in ROOTS:
        for p in root.rglob(en_name):
            return p
    return None

def read_en_status_map(en_path: Path):
    m = {}
    with en_path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return m
    try:
        id_idx = rows[0].index('Id')
        status_idx = rows[0].index('Status')
    except ValueError:
        return m
    for row in rows[1:]:
        if len(row) > id_idx:
            idval = row[id_idx].strip()
            stat = row[status_idx].strip() if len(row) > status_idx else ''
            if idval:
                m[idval] = stat
    return m


def fix_es_file(es_path: Path, en_map):
    changed = 0
    with es_path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return 0
    try:
        id_idx = rows[0].index('Id')
        status_idx = rows[0].index('Status')
    except ValueError:
        return 0
    for i in range(1, len(rows)):
        row = rows[i]
        if len(row) <= status_idx:
            row += [''] * (status_idx - len(row) + 1)
        if row[status_idx].strip() == '':
            idval = row[id_idx].strip() if len(row) > id_idx else ''
            if idval and idval in en_map and en_map[idval]:
                row[status_idx] = en_map[idval]
                changed += 1
    if changed:
        with es_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    return changed

if __name__ == '__main__':
    es_files = []
    for root in ROOTS:
        for p in root.rglob('*_es_*.csv'):
            es_files.append(p)
    es_files = sorted(set(es_files))
    total_files = len(es_files)
    total_changes = 0
    modified_files = []
    for es in es_files:
        en_name = es.name.replace('_es_', '_en_')
        en_path = find_en_file(en_name)
        if not en_path:
            continue
        en_map = read_en_status_map(en_path)
        if not en_map:
            continue
        changed = fix_es_file(es, en_map)
        if changed:
            total_changes += changed
            modified_files.append((str(es), changed, str(en_path)))
    print(f"Scanned {total_files} es-files; updated {len(modified_files)} files; total rows changed: {total_changes}")
    for m in modified_files:
        print(m[0], "=> rows changed:", m[1], "(source:", m[2], ")")
