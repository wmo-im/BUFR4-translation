import fitz
pdf_path = "/Users/omard/Documents/projects/WMO_work_claude/table_extractor_vision/french_pdfs/306_I2_2019_fr.pdf"
doc = fitz.open(pdf_path)

# Get the full text + spans for page 917 (033081)
page = doc[917]

# Get dict to see spans with positions
blocks = page.get_text("dict")["blocks"]
print("=== PAGE 917 spans with x-positions ===")
for block in blocks:
    if "lines" not in block:
        continue
    for line in block["lines"]:
        for span in line["spans"]:
            x = span["origin"][0]
            y = span["origin"][1]
            text = span["text"].strip()
            if text:
                print(f"  x={x:.0f} y={y:.0f}  '{text}'")

doc.close()
