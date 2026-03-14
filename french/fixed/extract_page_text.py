import fitz
import sys

pdf_path = "/Users/omard/Documents/projects/WMO_work_claude/table_extractor_vision/french_pdfs/306_I2_2019_fr.pdf"
doc = fitz.open(pdf_path)

pages_to_read = [
    ("011038", [806]),
    ("020003 (pg 824-826, where 80-85 would be)", [824, 825, 826]),
    ("020034", [838]),
    ("023007", [870]),
    ("033081", [917]),
]

for label, pages in pages_to_read:
    for pg_idx in pages:
        page = doc[pg_idx]
        text = page.get_text("text")
        print(f"\n{'='*60}")
        print(f"PAGE {pg_idx} (0-indexed) — {label}")
        print('='*60)
        print(text[:4000])
doc.close()
