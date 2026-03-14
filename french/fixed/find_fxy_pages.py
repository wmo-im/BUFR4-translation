import fitz
pdf_path = "/Users/omard/Documents/projects/WMO_work_claude/table_extractor_vision/french_pdfs/306_I2_2019_fr.pdf"
doc = fitz.open(pdf_path)
targets = {}
for fxy_raw in ["020003", "020034", "023007", "033081"]:
    f = fxy_raw[0]
    xx = int(fxy_raw[1:3])
    yyy = int(fxy_raw[3:])
    pattern = f"{f} {xx:02d} {yyy:03d}"
    for pg_idx in range(714, 937):
        page = doc[pg_idx]
        text = page.get_text("text")
        if pattern in text:
            if fxy_raw not in targets:
                targets[fxy_raw] = []
            targets[fxy_raw].append(pg_idx)
for fxy, pgs in targets.items():
    print(f"{fxy}: pages = {pgs}")
doc.close()
