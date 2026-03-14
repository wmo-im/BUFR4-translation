import fitz
pdf_path = "/Users/omard/Documents/projects/WMO_work_claude/table_extractor_vision/french_pdfs/306_I2_2019_fr.pdf"
doc = fitz.open(pdf_path)

# Page 820-823 for 020003 - find page with code figures 80-86
for pg_idx in [820, 821, 822, 823]:
    page = doc[pg_idx]
    text = page.get_text("text")
    print(f"\n{'='*60}")
    print(f"PAGE {pg_idx}")
    print('='*60)
    print(text[:5000])
doc.close()
