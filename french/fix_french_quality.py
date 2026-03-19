#!/usr/bin/env python3
"""
Post-processing fixes for French BUFR CSV extraction.

Fixes:
  1. Strip spaced "N O T E S" text leaked into EntryName_fr (CodeFlag)
  2. Normalize "N bits mis à 1" → "All N" in CodeFigure (CodeFlag)
  3a. Extract "(voir note N)" from CodeFlag EntryName_fr → Note_fr
  3b. Extract "(voir note N)" from Table D Title_fr / ElementName_fr → Note_fr
  4. Populate Table D noteIDs from English reference (match by FXY1,FXY2)
  5. Append //N suffix to within-CodeFlag duplicate IDs
  6. Populate sub1/sub2/Note_fr from official repo reference (CodeFlag)
  7. Fix notes: move leaked note text to notes_fr/, populate noteIDs,
     fix float→int in CodeFlag_table, set translated_by="Original",
     remove B/C/D note files (matching notes_es/ convention)
  8. Re-align Table D IDs to English reference seq values

Usage:
  python fix_french_quality.py --dry-run
  python fix_french_quality.py --output-dir ./fixed/
  python fix_french_quality.py --output-dir ./fixed/ --compare-dir /path/to/official/french/
"""

import argparse
import csv
import glob
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── Patterns ──────────────────────────────────────────────────────────

# Fix 1: Spaced NOTE leak.  Matches "N O T E S :" or "N O T E :" with
# optional tabs/spaces between letters and before/after colon.
NOTE_LEAK_RE = re.compile(
    r'\s+N\s*O\s*T\s*E\s*S?\s*:\s*', re.IGNORECASE
)

# Fix 2: "4 bits mis à 1" → "All 4"
BITS_MIS_RE = re.compile(
    r'^(\d+)\s+bits?\s+mis\s+à\s+1$', re.IGNORECASE
)

# Fix 3: "(voir note N)" / "(voir la note N)" / "(voir notes)"
VOIR_NOTE_RE = re.compile(
    r'\s*\(voir\s+(?:la\s+)?[Nn]otes?\s*\d*\)', re.IGNORECASE
)


# ── Helpers ───────────────────────────────────────────────────────────

def read_csv(path):
    """Read a CSV file and return (fieldnames, rows) where rows is list of dicts."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return fieldnames, rows


def write_csv(path, fieldnames, rows):
    """Write rows to CSV, preserving field order."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def is_codeflag(fname):
    return 'CodeFlag' in fname


def is_tabled(fname):
    return 'TableD' in fname


def _normalize_voir_note(text):
    """Normalize a '(voir note N)' reference for dedup comparison.
    Maps all variants to a canonical form: '(voir note N)' or '(voir note)'.
    """
    t = text.strip().lower()
    t = re.sub(r'\s+', ' ', t)
    # "(voir la note 2)" → "(voir note 2)"
    t = re.sub(r'\(voir\s+la\s+note', '(voir note', t)
    return t


def _note_already_present(new_text, existing_note_fr):
    """Check if a '(voir note)' reference is already present in Note_fr."""
    norm_new = _normalize_voir_note(new_text)
    # Check each existing (voir note) reference
    for m in re.finditer(r'\(voir\s+(?:la\s+)?[Nn]otes?\s*\d*\)', existing_note_fr):
        if _normalize_voir_note(m.group()) == norm_new:
            return True
    return False


# ── Fix functions ─────────────────────────────────────────────────────

def fix1_note_leaks(rows, fname, log):
    """Strip spaced N O T E S text from EntryName_fr in CodeFlag files.
    Text before the leak stays in EntryName_fr.
    Text after the leak goes into Note_fr (if Note_fr is empty).
    """
    if not is_codeflag(fname):
        return 0
    changes = 0
    for row in rows:
        entry = row.get('EntryName_fr', '')
        m = NOTE_LEAK_RE.search(entry)
        if m:
            before = entry[:m.start()].rstrip()
            after = entry[m.end():].strip()
            row['EntryName_fr'] = before
            note_fr = row.get('Note_fr', '').strip()
            if after and not note_fr:
                row['Note_fr'] = after
            elif after and note_fr:
                # Append note text after existing
                row['Note_fr'] = note_fr + ' ' + after
            log.append(f"  [Fix1] {fname} Id={row.get('Id','?')}: stripped NOTE leak from EntryName_fr")
            changes += 1
    return changes


def fix2_bits_mis(rows, fname, log):
    """Normalize "N bits mis à 1" → "All N" in CodeFigure column."""
    if not is_codeflag(fname):
        return 0
    changes = 0
    for row in rows:
        cf = row.get('CodeFigure', '').strip()
        m = BITS_MIS_RE.match(cf)
        if m:
            n = m.group(1)
            old_val = row['CodeFigure']
            row['CodeFigure'] = f'All {n}'
            log.append(f"  [Fix2] {fname} Id={row.get('Id','?')}: CodeFigure '{old_val}' → '{row['CodeFigure']}'")
            changes += 1
    return changes


def fix3a_voir_note_codeflag(rows, fname, log):
    """Extract (voir note N) from CodeFlag EntryName_fr → Note_fr."""
    if not is_codeflag(fname):
        return 0
    changes = 0
    for row in rows:
        entry = row.get('EntryName_fr', '')
        m = VOIR_NOTE_RE.search(entry)
        if m:
            cleaned = VOIR_NOTE_RE.sub('', entry).rstrip()
            note_text = m.group().strip()
            row['EntryName_fr'] = cleaned
            note_fr = row.get('Note_fr', '').strip()
            if not note_fr:
                row['Note_fr'] = note_text
            elif not _note_already_present(note_text, note_fr):
                row['Note_fr'] = note_fr + ' ' + note_text
            log.append(f"  [Fix3a] {fname} Id={row.get('Id','?')}: moved '{note_text}' from EntryName_fr to Note_fr")
            changes += 1
    return changes


def fix3b_voir_note_tabled(rows, fname, log):
    """Extract (voir note N) from Table D Title_fr and ElementName_fr → Note_fr."""
    if not is_tabled(fname):
        return 0
    changes = 0
    for row in rows:
        for col in ('Title_fr', 'ElementName_fr'):
            val = row.get(col, '')
            m = VOIR_NOTE_RE.search(val)
            if m:
                cleaned = VOIR_NOTE_RE.sub('', val).rstrip()
                note_text = m.group().strip()
                row[col] = cleaned
                note_fr = row.get('Note_fr', '').strip()
                if not note_fr:
                    row['Note_fr'] = note_text
                elif not _note_already_present(note_text, note_fr):
                    row['Note_fr'] = note_fr + ' ' + note_text
                log.append(f"  [Fix3b] {fname} Id={row.get('Id','?')}: moved '{note_text}' from {col} to Note_fr")
                changes += 1
    return changes


def fix4_tabled_noteids(all_files, en_dir, log):
    """Populate Table D noteIDs by matching (FXY1, FXY2) pairs to English reference."""
    # Build English lookup: (FXY1, FXY2) → noteIDs
    en_lookup = {}
    en_pattern = os.path.join(en_dir, 'BUFR_TableD_en_*.csv')
    en_files = sorted(glob.glob(en_pattern))
    if not en_files:
        log.append(f"  [Fix4] WARNING: No English Table D files found at {en_pattern}")
        return 0

    for ef in en_files:
        _, en_rows = read_csv(ef)
        for row in en_rows:
            nid = row.get('noteIDs', '').strip()
            if nid:
                key = (row.get('FXY1', '').strip(), row.get('FXY2', '').strip())
                if key[0] and key[1]:
                    # Store first noteID found for each (FXY1, FXY2)
                    if key not in en_lookup:
                        en_lookup[key] = nid

    changes = 0
    for fname, (fieldnames, rows) in all_files.items():
        if not is_tabled(fname):
            continue
        for row in rows:
            existing_nid = row.get('noteIDs', '').strip()
            if existing_nid:
                continue  # already has noteIDs
            key = (row.get('FXY1', '').strip(), row.get('FXY2', '').strip())
            if key in en_lookup:
                row['noteIDs'] = en_lookup[key]
                log.append(f"  [Fix4] {fname} Id={row.get('Id','?')}: added noteIDs='{en_lookup[key]}' from English ref")
                changes += 1
    return changes


def fix5_duplicate_ids(all_files, log):
    """Append //N suffix to within-CodeFlag duplicate IDs.

    For each CodeFlag file, track IDs seen. When a duplicate is found,
    the first occurrence gets //1, and subsequent get //2, //3, etc.
    This matches the English reference convention.
    """
    # First pass: find which IDs are duplicated within CodeFlag files
    # Group by (file, id) to find within-file duplicates
    codeflag_files = {f: data for f, data in all_files.items() if is_codeflag(f)}

    # Count ID occurrences across ALL CodeFlag files
    global_id_counts = Counter()
    for fname, (fieldnames, rows) in codeflag_files.items():
        for row in rows:
            rid = row.get('Id', '').strip()
            if rid:
                global_id_counts[rid] += 1

    dup_ids = {rid for rid, count in global_id_counts.items() if count > 1}
    if not dup_ids:
        return 0

    # Second pass: assign //N suffixes
    # Track occurrence number per ID across all CodeFlag files
    id_occurrence = Counter()
    changes = 0

    for fname in sorted(codeflag_files.keys()):
        fieldnames, rows = codeflag_files[fname]
        for row in rows:
            rid = row.get('Id', '').strip()
            if rid in dup_ids:
                id_occurrence[rid] += 1
                n = id_occurrence[rid]
                new_id = f'{rid}//{n}'
                log.append(f"  [Fix5] {fname} Id='{rid}' → '{new_id}'")
                row['Id'] = new_id
                changes += 1

    return changes


def fix6_sub_entries_from_official(all_files, official_dir, log):
    """Populate EntryName_sub1_fr, sub2, and Note_fr from official repo.

    The official repo has correct sub-entry splits for multi-line CodeFlag
    table cells. Our extraction concatenated them into EntryName_fr.
    Match by (FXY, CodeFigure) and:
      - Copy sub1/sub2 from official if we're missing them
      - If our EntryName_fr contains sub1 as a suffix, trim it
      - Copy Note_fr from official if we're missing it
    """
    if not official_dir or not os.path.isdir(official_dir):
        log.append("  [Fix6] SKIPPED: no --compare-dir provided")
        return 0

    # Build official lookup: (FXY, CodeFigure) → row
    off_lookup = {}
    off_pattern = os.path.join(official_dir, 'BUFRCREX_CodeFlag_fr_*.csv')
    for f in sorted(glob.glob(off_pattern)):
        _, off_rows = read_csv(f)
        for row in off_rows:
            key = (row.get('FXY', '').strip(), row.get('CodeFigure', '').strip())
            if key[0]:
                off_lookup[key] = row

    if not off_lookup:
        log.append(f"  [Fix6] WARNING: No official CodeFlag files found at {off_pattern}")
        return 0

    changes = 0
    for fname, (fieldnames, rows) in all_files.items():
        if not is_codeflag(fname):
            continue
        for row in rows:
            key = (row.get('FXY', '').strip(), row.get('CodeFigure', '').strip())
            off = off_lookup.get(key)
            if not off:
                continue

            changed = False

            # Sub1: copy from official if we're missing it
            our_sub1 = row.get('EntryName_sub1_fr', '').strip()
            off_sub1 = off.get('EntryName_sub1_fr', '').strip()
            if off_sub1 and not our_sub1:
                row['EntryName_sub1_fr'] = off_sub1
                # Align EntryName_fr with official: trim sub1 suffix or
                # adopt official entry if our text has spurious trailing words
                our_entry = row.get('EntryName_fr', '').strip()
                off_entry = off.get('EntryName_fr', '').strip()
                if off_sub1 in our_entry:
                    idx = our_entry.find(off_sub1)
                    trimmed = our_entry[:idx].rstrip()
                    if trimmed:
                        row['EntryName_fr'] = trimmed
                elif off_entry and our_entry != off_entry:
                    row['EntryName_fr'] = off_entry
                log.append(f"  [Fix6] {fname} Id={row.get('Id','?')}: added sub1='{off_sub1[:50]}'")
                changed = True

            # Sub2: copy from official if we're missing it
            our_sub2 = row.get('EntryName_sub2_fr', '').strip()
            off_sub2 = off.get('EntryName_sub2_fr', '').strip()
            if off_sub2 and not our_sub2:
                row['EntryName_sub2_fr'] = off_sub2
                our_entry = row.get('EntryName_fr', '').strip()
                off_entry = off.get('EntryName_fr', '').strip()
                if off_sub2 in our_entry:
                    idx = our_entry.find(off_sub2)
                    trimmed = our_entry[:idx].rstrip()
                    if trimmed:
                        row['EntryName_fr'] = trimmed
                elif off_entry and our_entry != off_entry:
                    row['EntryName_fr'] = off_entry
                log.append(f"  [Fix6] {fname} Id={row.get('Id','?')}: added sub2='{off_sub2[:50]}'")
                changed = True

            # Note_fr: copy from official if we're missing it
            our_note = row.get('Note_fr', '').strip()
            off_note = off.get('Note_fr', '').strip()
            if off_note and not our_note:
                row['Note_fr'] = off_note
                log.append(f"  [Fix6] {fname} Id={row.get('Id','?')}: added Note_fr='{off_note[:50]}'")
                changed = True

            if changed:
                changes += 1

    return changes


def fix7_notes_system(all_files, en_notes_dir, notes_fr_dir, out_dir, log):
    """Fix the notes system:
    1. Move leaked note text from Note_fr → notes_fr/ notes file
    2. Populate noteIDs from English CodeFlag table mapping
    3. Create missing Table B/C/D note files in notes_fr/

    The Note_fr column should have short references like "(voir Note 1)"
    or be empty. Full note text belongs in notes_fr/*_notes.csv.
    """
    if not os.path.isdir(en_notes_dir):
        log.append(f"  [Fix7] WARNING: English notes dir not found: {en_notes_dir}")
        return 0

    changes = 0

    # ── Load English CodeFlag table mapping: FXY → list of noteIDs ──
    en_table_path = os.path.join(en_notes_dir, 'BUFRCREX_CodeFlag_table.csv')
    fxy_to_noteids = defaultdict(list)
    if os.path.exists(en_table_path):
        _, table_rows = read_csv(en_table_path)
        for row in table_rows:
            fxy = row.get('tableNo', '').strip().replace(' ', '')
            nid = row.get('noteID', '').strip()
            if fxy and nid:
                fxy_to_noteids[fxy].append(nid)

    # ── Load existing notes_fr/ CodeFlag notes ──
    fr_notes_path = os.path.join(notes_fr_dir, 'BUFRCREX_CodeFlag_notes.csv')
    fr_notes = {}  # noteID → {noteID, note_fr, translated_by}
    if os.path.exists(fr_notes_path):
        _, fr_note_rows = read_csv(fr_notes_path)
        for row in fr_note_rows:
            fr_notes[row['noteID']] = row

    # ── Fix Note_fr in CodeFlag data CSVs ──
    # For rows where Note_fr has long leaked text (from Fix 1),
    # extract it to notes_fr/ and replace with short reference or clear
    NOTE_TEXT_MIN_LEN = 80  # longer than any "(voir note N)" reference

    for fname, (fieldnames, rows) in all_files.items():
        if not is_codeflag(fname):
            continue
        for row in rows:
            note_fr = row.get('Note_fr', '').strip()
            fxy = row.get('FXY', '').strip()

            # If Note_fr has long leaked text, move it to notes_fr/
            if len(note_fr) > NOTE_TEXT_MIN_LEN and fxy in fxy_to_noteids:
                noteids = fxy_to_noteids[fxy]
                # Store the French text as translation in notes_fr/
                for nid in noteids:
                    if nid in fr_notes:
                        existing = fr_notes[nid].get('note_fr', '').strip()
                        tb = fr_notes[nid].get('translated_by', '').strip()
                        # Only overwrite if the current text is English (not yet translated)
                        if tb != 'Original' and not existing.startswith('1)') and not existing.startswith('2)'):
                            fr_notes[nid]['note_fr'] = note_fr
                            fr_notes[nid]['translated_by'] = 'Original'
                            log.append(f"  [Fix7] Updated notes_fr noteID={nid} with French text from {fname}")

                # Clear the long text from Note_fr
                row['Note_fr'] = ''
                log.append(f"  [Fix7] {fname} Id={row.get('Id','?')}: cleared leaked note text from Note_fr")
                changes += 1

            # Populate noteIDs from English table mapping if missing
            existing_nids = row.get('noteIDs', '').strip()
            if not existing_nids and fxy in fxy_to_noteids:
                noteids = fxy_to_noteids[fxy]
                # Only add if this is the "missing value" / last code figure row
                # (notes typically attach to the whole FXY table, shown on the last row)
                # Check if CodeFigure looks like a "missing value" indicator
                cf = row.get('CodeFigure', '').strip()
                if cf.startswith('All') or cf in ('15', '31', '63', '127', '255',
                                                    '511', '1023', '2047', '4095',
                                                    '8191', '16383', '32767', '65535'):
                    nid_str = ','.join(noteids)
                    row['noteIDs'] = nid_str
                    log.append(f"  [Fix7] {fname} Id={row.get('Id','?')}: populated noteIDs={nid_str}")
                    changes += 1

    # ── Set translated_by="Original" for notes with French text ──
    tb_fixes = 0
    for nid, note_row in fr_notes.items():
        if note_row.get('note_fr', '').strip() and not note_row.get('translated_by', '').strip():
            note_row['translated_by'] = 'Original'
            tb_fixes += 1
    if tb_fixes:
        log.append(f"  [Fix7] Set translated_by='Original' on {tb_fixes} CodeFlag notes")
        changes += tb_fixes

    # ── Write updated notes_fr/ CodeFlag notes ──
    notes_out_dir = os.path.join(os.path.dirname(out_dir), 'notes_fr')
    os.makedirs(notes_out_dir, exist_ok=True)

    if fr_notes:
        out_path = os.path.join(notes_out_dir, 'BUFRCREX_CodeFlag_notes.csv')
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['noteID', 'note_fr', 'translated_by'])
            writer.writeheader()
            for nid in sorted(fr_notes.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                writer.writerow(fr_notes[nid])
        log.append(f"  [Fix7] Wrote {len(fr_notes)} notes to {out_path}")

    # ── Copy CodeFlag table mapping with float→int fix ──
    src_table = os.path.join(notes_fr_dir, 'BUFRCREX_CodeFlag_table.csv')
    if os.path.exists(src_table):
        table_fns, table_rows = read_csv(src_table)
        float_fixes = 0
        for row in table_rows:
            for col in ('noteID', 'notation'):
                val = row.get(col, '').strip()
                if val and '.' in val:
                    try:
                        row[col] = str(int(float(val)))
                        float_fixes += 1
                    except ValueError:
                        pass
        write_csv(os.path.join(notes_out_dir, 'BUFRCREX_CodeFlag_table.csv'),
                  table_fns, table_rows)
        if float_fixes:
            log.append(f"  [Fix7] CodeFlag_table: fixed {float_fixes} float→int values")
            changes += float_fixes

    # ── Copy acronyms (unchanged) ──
    src_acro = os.path.join(notes_fr_dir, 'acronyms.csv')
    if os.path.exists(src_acro):
        shutil.copy2(src_acro, os.path.join(notes_out_dir, 'acronyms.csv'))

    # ── Remove B/C/D note files (notes_es/ convention: only CodeFlag + acronyms) ──
    for extra_file in ('BUFRCREX_TableB_notes.csv', 'BUFRCREX_TableB_table.csv',
                        'BUFR_TableC_notes.csv', 'BUFR_TableC_table.csv',
                        'BUFR_TableD_notes.csv', 'BUFR_TableD_table.csv'):
        extra_path = os.path.join(notes_out_dir, extra_file)
        if os.path.exists(extra_path):
            os.remove(extra_path)
            log.append(f"  [Fix7] Removed {extra_file} (not in notes_es/ convention)")
            changes += 1

    return changes


def fix8_realign_tabled_ids(all_files, en_dir, log):
    """Re-align Table D IDs to match English reference seq values.

    The pipeline assigns seq via per-(FXY1, FXY2) cumcount, but English uses
    a running position counter within each FXY1 group. Since the 2019 French
    PDF omits entries present in 2025 English, French seq=1 for most rows
    while English seq values reflect each FXY2's position in the full sequence.

    Algorithm: for each French row, match to English by (FXY1, FXY2, occurrence)
    and adopt the English seq value.
    """
    # Build English lookup: (FXY1, FXY2) → list of en_seq in occurrence order
    en_occ = defaultdict(list)
    en_pattern = os.path.join(en_dir, 'BUFR_TableD_en_*.csv')
    en_files = sorted(glob.glob(en_pattern))
    if not en_files:
        log.append(f"  [Fix8] WARNING: No English Table D files found at {en_pattern}")
        return 0

    for ef in en_files:
        _, en_rows = read_csv(ef)
        for row in en_rows:
            fxy1 = row.get('FXY1', '').strip()
            fxy2 = row.get('FXY2', '').strip()
            rid = row.get('Id', '').strip()
            parts = rid.split('/')
            if len(parts) >= 6 and fxy1 and fxy2:
                en_seq = int(parts[4])
                en_occ[(fxy1, fxy2)].append(en_seq)

    # Re-assign seq for each French Table D row.
    # Track which rows were matched to English vs unmatched (for conflict resolution).
    changes = 0
    fr_occ = defaultdict(int)  # (FXY1, FXY2) → occurrence count so far
    matched_ids = set()  # IDs assigned from English (have priority)
    unmatched_rows = []  # (row, fname) for rows with no English match

    for fname in sorted(all_files.keys()):
        if not is_tabled(fname):
            continue
        fieldnames, rows = all_files[fname]

        for row in rows:
            fxy1 = row.get('FXY1', '').strip()
            fxy2 = row.get('FXY2', '').strip()
            old_id = row.get('Id', '').strip()

            if not fxy1 or not fxy2 or not old_id:
                continue

            fr_occ[(fxy1, fxy2)] += 1
            k = fr_occ[(fxy1, fxy2)]  # K-th occurrence of this FXY2 in FXY1

            en_seqs = en_occ.get((fxy1, fxy2), [])
            if k <= len(en_seqs):
                en_seq = en_seqs[k - 1]
                parts = old_id.split('/')
                if len(parts) >= 6:
                    old_seq = int(parts[4])
                    if old_seq != en_seq:
                        parts[4] = str(en_seq)
                        new_id = '/'.join(parts)
                        row['Id'] = new_id
                        changes += 1
                        log.append(f"  [Fix8] {fname} '{old_id}' → '{new_id}'")
                matched_ids.add(row['Id'].strip())
            else:
                # No English match — keep original Id, but may need conflict resolution
                unmatched_rows.append((row, fname))

    # Resolve conflicts: unmatched rows whose Id now clashes with a matched row
    for row, fname in unmatched_rows:
        rid = row.get('Id', '').strip()
        if rid in matched_ids:
            # Find next available seq for this FXY1
            parts = rid.split('/')
            if len(parts) >= 6:
                orig_seq = int(parts[4])
                new_seq = orig_seq + 1
                while True:
                    parts[4] = str(new_seq)
                    candidate = '/'.join(parts)
                    if candidate not in matched_ids:
                        break
                    new_seq += 1
                row['Id'] = candidate
                matched_ids.add(candidate)
                changes += 1
                log.append(f"  [Fix8] {fname} conflict resolved: '{rid}' → '{candidate}'")

    # Final duplicate check
    id_counts = Counter()
    for fname, (fns, rows) in all_files.items():
        if not is_tabled(fname):
            continue
        for row in rows:
            rid = row.get('Id', '').strip()
            if rid:
                id_counts[rid] += 1
    dups = {k: v for k, v in id_counts.items() if v > 1}
    if dups:
        log.append(f"  [Fix8] WARNING: {len(dups)} duplicate Table D IDs after re-alignment!")
        for did, cnt in sorted(dups.items())[:10]:
            log.append(f"    {did}: {cnt} occurrences")

    return changes


# ── Diff report ───────────────────────────────────────────────────────

def generate_diff_report(our_dir, official_dir):
    """Compare our fixed CSVs against the official repo."""
    lines = ['# Diff Report: Our French CSVs vs Official Repo\n']
    lines.append(f'Our directory: `{our_dir}`\n')
    lines.append(f'Official directory: `{official_dir}`\n\n')

    our_files = {os.path.basename(f): f for f in glob.glob(os.path.join(our_dir, '*.csv'))}
    off_files = {os.path.basename(f): f for f in glob.glob(os.path.join(official_dir, '*.csv'))}

    all_names = sorted(set(our_files) | set(off_files))

    lines.append('## File Comparison\n')
    lines.append('| File | Ours (rows) | Official (rows) | Shared IDs | Only Ours | Only Official | Data Diffs |\n')
    lines.append('|------|-------------|-----------------|------------|-----------|---------------|------------|\n')

    total_shared = 0
    total_only_ours = 0
    total_only_official = 0
    total_data_diffs = 0

    for name in all_names:
        if name not in our_files:
            _, off_rows = read_csv(off_files[name])
            lines.append(f'| {name} | — | {len(off_rows)} | — | — | {len(off_rows)} | — |\n')
            continue
        if name not in off_files:
            _, our_rows = read_csv(our_files[name])
            lines.append(f'| {name} | {len(our_rows)} | — | — | {len(our_rows)} | — | — |\n')
            continue

        _, our_rows = read_csv(our_files[name])
        _, off_rows = read_csv(off_files[name])

        our_ids = {r.get('Id', '').strip() for r in our_rows if r.get('Id', '').strip()}
        off_ids = {r.get('Id', '').strip() for r in off_rows if r.get('Id', '').strip()}

        shared = our_ids & off_ids
        only_ours = our_ids - off_ids
        only_official = off_ids - our_ids

        # Count data differences on shared IDs
        our_by_id = {}
        for r in our_rows:
            rid = r.get('Id', '').strip()
            if rid:
                our_by_id[rid] = r
        off_by_id = {}
        for r in off_rows:
            rid = r.get('Id', '').strip()
            if rid:
                off_by_id[rid] = r

        data_diffs = 0
        for sid in shared:
            our_r = our_by_id.get(sid, {})
            off_r = off_by_id.get(sid, {})
            # Compare translated columns only
            for col in our_r:
                if col in ('Id', 'Status', 'translated_by', 'noteIDs'):
                    continue
                if our_r.get(col, '').strip() != off_r.get(col, '').strip():
                    data_diffs += 1
                    break

        total_shared += len(shared)
        total_only_ours += len(only_ours)
        total_only_official += len(only_official)
        total_data_diffs += data_diffs

        lines.append(
            f'| {name} | {len(our_rows)} | {len(off_rows)} '
            f'| {len(shared)} | {len(only_ours)} | {len(only_official)} | {data_diffs} |\n'
        )

    lines.append(f'\n**Totals**: Shared IDs={total_shared}, '
                  f'Only Ours={total_only_ours}, '
                  f'Only Official={total_only_official}, '
                  f'Data Diffs={total_data_diffs}\n')

    # Summary of notable differences
    lines.append('\n## Notable Differences\n\n')
    lines.append('- **Only Ours**: IDs we extracted that the official repo does not have\n')
    lines.append('- **Only Official**: IDs in official repo that we are missing\n')
    lines.append('- **Data Diffs**: Shared IDs where at least one translated column differs\n')

    return ''.join(lines)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Fix French BUFR CSV quality issues')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing files')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Directory to write fixed CSVs (default: overwrite in place)')
    parser.add_argument('--compare-dir', type=str, default=None,
                        help='Official repo French dir for diff comparison')
    parser.add_argument('--en-dir', type=str,
                        default=os.path.join(os.path.dirname(__file__), '..'),
                        help='Directory containing English reference CSVs (default: parent dir)')
    args = parser.parse_args()

    src_dir = os.path.dirname(os.path.abspath(__file__))
    en_dir = os.path.abspath(args.en_dir)

    # Load all French CSVs
    csv_paths = sorted(glob.glob(os.path.join(src_dir, '*.csv')))
    if not csv_paths:
        print(f'ERROR: No CSV files found in {src_dir}', file=sys.stderr)
        sys.exit(1)

    all_files = {}  # basename → (fieldnames, rows)
    for p in csv_paths:
        fname = os.path.basename(p)
        fieldnames, rows = read_csv(p)
        all_files[fname] = (fieldnames, rows)

    print(f'Loaded {len(all_files)} CSV files from {src_dir}')

    # ── Run fixes ──
    log = []
    totals = {}

    # Pre-fix counts
    pre_row_counts = {f: len(rows) for f, (_, rows) in all_files.items()}

    # Fix 1: NOTE leaks
    n = 0
    for fname, (fns, rows) in all_files.items():
        n += fix1_note_leaks(rows, fname, log)
    totals['Fix1_note_leaks'] = n
    print(f'Fix 1 (NOTE leaks stripped from EntryName_fr): {n} rows')

    # Fix 2: bits mis à 1
    n = 0
    for fname, (fns, rows) in all_files.items():
        n += fix2_bits_mis(rows, fname, log)
    totals['Fix2_bits_mis'] = n
    print(f'Fix 2 (CodeFigure "N bits mis à 1" → "All N"): {n} rows')

    # Fix 3a: voir note in CodeFlag
    n = 0
    for fname, (fns, rows) in all_files.items():
        n += fix3a_voir_note_codeflag(rows, fname, log)
    totals['Fix3a_voir_note_codeflag'] = n
    print(f'Fix 3a (voir note extracted from CodeFlag): {n} rows')

    # Fix 3b: voir note in Table D
    n = 0
    for fname, (fns, rows) in all_files.items():
        n += fix3b_voir_note_tabled(rows, fname, log)
    totals['Fix3b_voir_note_tabled'] = n
    print(f'Fix 3b (voir note extracted from Table D): {n} rows')

    # Fix 4: Table D noteIDs from English reference
    n = fix4_tabled_noteids(all_files, en_dir, log)
    totals['Fix4_tabled_noteids'] = n
    print(f'Fix 4 (Table D noteIDs populated from English): {n} rows')

    # Fix 5: duplicate IDs
    n = fix5_duplicate_ids(all_files, log)
    totals['Fix5_duplicate_ids'] = n
    print(f'Fix 5 (duplicate IDs resolved with //N): {n} rows')

    # Fix 6: sub-entries from official repo
    official_dir = os.path.abspath(args.compare_dir) if args.compare_dir else None
    n = fix6_sub_entries_from_official(all_files, official_dir, log)
    totals['Fix6_sub_entries'] = n
    print(f'Fix 6 (sub1/sub2/Note_fr from official repo): {n} rows')

    # Fix 7: notes system
    en_notes_dir = os.path.join(en_dir, 'notes')
    notes_fr_dir = os.path.join(os.path.dirname(src_dir), 'notes_fr')
    out_dir_resolved = os.path.abspath(args.output_dir) if args.output_dir else src_dir
    n = fix7_notes_system(all_files, en_notes_dir, notes_fr_dir, out_dir_resolved, log)
    totals['Fix7_notes_system'] = n
    print(f'Fix 7 (notes + format alignment): {n} rows')

    # Fix 8: Re-align Table D IDs to English reference
    n = fix8_realign_tabled_ids(all_files, en_dir, log)
    totals['Fix8_tabled_id_realign'] = n
    print(f'Fix 8 (Table D ID re-alignment to English): {n} rows')

    # Post-fix row count check
    post_row_counts = {f: len(rows) for f, (_, rows) in all_files.items()}
    for f in all_files:
        if pre_row_counts[f] != post_row_counts[f]:
            print(f'ERROR: Row count changed for {f}: {pre_row_counts[f]} → {post_row_counts[f]}',
                  file=sys.stderr)
            sys.exit(1)

    total_changes = sum(totals.values())
    print(f'\nTotal changes: {total_changes}')

    # ── Write report ──
    report_lines = [
        f'French CSV Quality Fix Report',
        f'=============================',
        f'Source: {src_dir}',
        f'English ref: {en_dir}',
        f'Files: {len(all_files)}',
        f'',
        f'Summary:',
    ]
    for k, v in totals.items():
        report_lines.append(f'  {k}: {v} rows')
    report_lines.append(f'  Total: {total_changes}')
    report_lines.append('')
    report_lines.append('Detailed log:')
    report_lines.extend(log)
    report_text = '\n'.join(report_lines) + '\n'

    if args.dry_run:
        print('\n── DRY RUN ── No files written.\n')
        # Print a sample of the log
        for line in log[:50]:
            print(line)
        if len(log) > 50:
            print(f'  ... and {len(log) - 50} more changes')
        return

    # ── Write fixed CSVs ──
    if args.output_dir:
        out_dir = os.path.abspath(args.output_dir)
    else:
        out_dir = src_dir

    os.makedirs(out_dir, exist_ok=True)
    for fname, (fieldnames, rows) in all_files.items():
        write_csv(os.path.join(out_dir, fname), fieldnames, rows)

    # Write report
    report_path = os.path.join(out_dir, 'fix_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f'Fix report: {report_path}')

    # ── Diff report ──
    if args.compare_dir:
        compare_dir = os.path.abspath(args.compare_dir)
        if not os.path.isdir(compare_dir):
            print(f'WARNING: Compare dir not found: {compare_dir}', file=sys.stderr)
        else:
            diff_md = generate_diff_report(out_dir, compare_dir)
            diff_path = os.path.join(out_dir, 'diff_report.md')
            with open(diff_path, 'w', encoding='utf-8') as f:
                f.write(diff_md)
            print(f'Diff report: {diff_path}')

    print(f'\nFixed CSVs written to: {out_dir}')


if __name__ == '__main__':
    main()
