#!/usr/bin/env python3
"""
QC Script for BUFR4-translation Repository (Updated)
Verifies that Id values in Spanish files match their corresponding English files.
Spanish files may have fewer rows (incomplete translations), so we only check
the Ids that exist in BOTH files.
"""

import csv
import os
import sys
from pathlib import Path
from collections import defaultdict


def read_ids_from_csv(filepath):
    """Read the Id column from a CSV file with line numbers."""
    ids = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if 'Id' not in reader.fieldnames:
                print(f"WARNING: No 'Id' column found in {filepath}")
                return None
            for line_num, row in enumerate(reader, start=2):  # Line 2 is first data row
                ids.append({
                    'id': row['Id'],
                    'line': line_num
                })
        return ids
    except Exception as e:
        print(f"ERROR reading {filepath}: {e}")
        return None


def find_file_pairs(directory):
    """
    Find matching English and Spanish file pairs.
    Returns a list of tuples: (en_file, es_file, base_name)
    """
    pairs = []
    
    # Get all English files
    en_files = list(Path(directory).glob('*_en_*.csv'))
    
    for en_file in en_files:
        # Construct the expected Spanish filename
        es_filename = en_file.name.replace('_en_', '_es_')
        es_file = en_file.parent / es_filename
        
        # Also check in spanish/ subdirectory
        spanish_subdir = en_file.parent / 'spanish'
        es_file_in_subdir = spanish_subdir / es_filename
        
        if es_file.exists():
            pairs.append((str(en_file), str(es_file), en_file.stem))
        elif es_file_in_subdir.exists():
            pairs.append((str(en_file), str(es_file_in_subdir), en_file.stem))
    
    return sorted(pairs)


def compare_ids_detailed(en_ids, es_ids, en_file, es_file):
    """
    Compare Ids that exist in both files and report mismatches.
    Spanish files may have fewer rows, which is OK.
    We only flag issues where:
    1. An Id exists in both files but has a different value
    2. An Id that exists in Spanish doesn't exist in English (this would be unusual)
    
    Returns (is_match, report_dict)
    """
    if en_ids is None or es_ids is None:
        return False, {"error": "Could not read one or both files"}
    
    report = {
        'en_count': len(en_ids),
        'es_count': len(es_ids),
        'id_mismatches': [],
        'only_in_spanish': []
    }
    
    # Create dictionaries for lookup: id -> line_number
    en_dict = {item['id']: item['line'] for item in en_ids}
    es_dict = {item['id']: item['line'] for item in es_ids}
    
    # Check if there are any IDs in Spanish that don't exist in English (unusual)
    es_set = set(es_dict.keys())
    en_set = set(en_dict.keys())
    only_in_es = es_set - en_set
    
    if only_in_es:
        report['only_in_spanish'] = [
            {
                'id': id_val,
                'es_line': es_dict[id_val]
            }
            for id_val in sorted(only_in_es)
        ]
    
    # Now check each Spanish Id to see if it matches the English Id at the same position
    for i, es_item in enumerate(es_ids):
        es_id = es_item['id']
        es_line = es_item['line']
        
        # Get the corresponding English Id at the same position (if exists)
        if i < len(en_ids):
            en_id = en_ids[i]['id']
            en_line = en_ids[i]['line']
            
            # Compare
            if en_id != es_id:
                report['id_mismatches'].append({
                    'position': i + 1,
                    'en_line': en_line,
                    'es_line': es_line,
                    'en_id': en_id,
                    'es_id': es_id
                })
    
    is_match = len(report['id_mismatches']) == 0 and len(report['only_in_spanish']) == 0
    return is_match, report


def main():
    # Check command line arguments
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = '.'
    
    directory = os.path.abspath(directory)
    print(f"QC Check: BUFR4-translation Repository")
    print(f"Checking for Id mismatches in existing rows")
    print(f"=" * 80)
    print(f"Directory: {directory}")
    print(f"=" * 80)
    print()
    
    # Find all file pairs
    pairs = find_file_pairs(directory)
    
    if not pairs:
        print("ERROR: No English-Spanish file pairs found!")
        print("Make sure you're running this in the repository root directory.")
        sys.exit(1)
    
    print(f"Found {len(pairs)} file pairs to check\n")
    
    # Track results
    results = {
        'passed': [],
        'failed': []
    }
    
    # Check each pair
    for en_file, es_file, base_name in pairs:
        en_ids = read_ids_from_csv(en_file)
        es_ids = read_ids_from_csv(es_file)
        
        is_match, report = compare_ids_detailed(en_ids, es_ids, en_file, es_file)
        
        if is_match:
            results['passed'].append({
                'name': base_name,
                'en_count': report['en_count'],
                'es_count': report['es_count']
            })
            print(f"✓ PASS: {base_name} (EN:{report['en_count']} rows, ES:{report['es_count']} rows)")
        else:
            results['failed'].append({
                'name': base_name,
                'en_file': en_file,
                'es_file': es_file,
                'report': report
            })
            mismatch_count = len(report['id_mismatches'])
            unusual_count = len(report['only_in_spanish'])
            print(f"✗ FAIL: {base_name} ({mismatch_count} mismatches, {unusual_count} unusual)")
    
    # Print summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total files checked: {len(pairs)}")
    print(f"Passed: {len(results['passed'])}")
    print(f"Failed: {len(results['failed'])}")
    print()
    
    # Print detailed failures
    if results['failed']:
        print("=" * 80)
        print("DETAILED FAILURE REPORT")
        print("=" * 80)
        
        for failure in results['failed']:
            print()
            print(f"{'=' * 80}")
            print(f"File: {failure['name']}")
            print(f"{'=' * 80}")
            print(f"  English: {failure['en_file']}")
            print(f"  Spanish: {failure['es_file']}")
            
            report = failure['report']
            print(f"  English rows: {report['en_count']}")
            print(f"  Spanish rows: {report['es_count']}")
            print(f"  Missing translations: {report['en_count'] - report['es_count']}")
            print()
            
            # Report Id mismatches
            if report['id_mismatches']:
                print(f"  ID MISMATCHES ({len(report['id_mismatches'])} total):")
                print(f"  {'Pos':<6} {'EN Line':<10} {'ES Line':<10} {'English ID':<45} {'Spanish ID':<45}")
                print(f"  {'-' * 116}")
                
                for mismatch in report['id_mismatches']:
                    pos = mismatch['position']
                    en_line = mismatch['en_line']
                    es_line = mismatch['es_line']
                    en_id = mismatch['en_id']
                    es_id = mismatch['es_id']
                    
                    print(f"  {pos:<6} {en_line:<10} {es_line:<10} {en_id:<45} {es_id:<45}")
            
            # Report unusual cases (IDs in Spanish but not in English)
            if report['only_in_spanish']:
                print()
                print(f"  UNUSUAL: IDs in Spanish but not in English ({len(report['only_in_spanish'])} total):")
                for item in report['only_in_spanish']:
                    print(f"    Line {item['es_line']}: {item['id']}")
    
    # Exit with appropriate code
    sys.exit(0 if len(results['failed']) == 0 else 1)


if __name__ == '__main__':
    main()
