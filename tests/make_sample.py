"""Tạo file PDF y khoa mẫu (2 cột, tiêu đề, chú thích, hình có chữ, công thức, tài liệu tham khảo) để kiểm thử."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _figure_png() -> bytes:
    img = Image.new("RGB", (600, 360), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 22)
    d.rectangle((40, 60, 260, 300), outline="black", width=3)
    d.rectangle((340, 60, 560, 300), outline="black", width=3, fill=(230, 240, 255))
    d.text((60, 20), "Left ventricle", font=f, fill="black")
    d.text((360, 20), "Right ventricle", font=f, fill="black")
    d.text((70, 160), "Normal heart", font=f, fill=(180, 0, 0))
    d.text((360, 160), "Heart failure", font=f, fill=(0, 0, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make(path: str | Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 40), "Textbook of Clinical Cardiology", fontsize=8, fontname="tiro")
    page.insert_textbox(pymupdf.Rect(50, 60, 545, 100), "Chapter 3. Heart Failure", fontsize=20, fontname="tibo")
    left = ("Heart failure is a clinical syndrome caused by structural or functional cardiac abnormalities. "
            "Patients typically present with dyspnea, fatigue and edema. The left ventricular ejection fraction "
            "(LVEF) should be measured by echocardiography in all patients with suspected heart failure. "
            "Furosemide 40 mg IV is recommended as the initial dose, and the dose may be increased to 80 mg "
            "if the response is inadequate.")
    right = ("Beta-blockers are not recommended in patients with acute decompensated heart failure and "
             "hypotension (systolic blood pressure < 90 mmHg). In the PARADIGM-HF trial, sacubitril/valsartan "
             "reduced mortality by 20% (hazard ratio 0.80; 95% CI 0.73-0.87; p < 0.001) [12]. Serum BNP "
             "levels above 100 pg/mL support the diagnosis.")
    page.insert_textbox(pymupdf.Rect(50, 120, 290, 400), left, fontsize=10, fontname="tiro", align=3)
    page.insert_textbox(pymupdf.Rect(305, 120, 545, 400), right, fontsize=10, fontname="tiro", align=3)
    page.insert_textbox(pymupdf.Rect(50, 410, 545, 440), "Key points", fontsize=12, fontname="tibo")
    page.insert_textbox(pymupdf.Rect(50, 440, 545, 470),
                        "BMI = weight (kg) / height (m)2  ;  CrCl = (140 - age) x weight / (72 x SCr)",
                        fontsize=10, fontname="tiro")
    page.insert_image(pymupdf.Rect(150, 480, 450, 660), stream=_figure_png())
    page.insert_textbox(pymupdf.Rect(50, 670, 545, 700),
                        "Figure 3.1 Comparison of a normal heart and a heart with reduced ejection fraction.",
                        fontsize=9, fontname="tiit")
    page.insert_text((290, 820), "45", fontsize=8, fontname="tiro")

    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(50, 60, 545, 90), "Treatment", fontsize=16, fontname="tibo")
    page.insert_textbox(pymupdf.Rect(50, 95, 545, 200),
                        "Staphylococcus aureus infection should be treated with vancomycin 15-20 mg/kg every "
                        "8-12 hours. Do not use aminoglycosides without monitoring serum creatinine. "
                        "Avoid NSAIDs in patients with chronic kidney disease.", fontsize=10, fontname="tiro")
    page.insert_textbox(pymupdf.Rect(50, 220, 545, 245), "References", fontsize=14, fontname="tibo")
    page.insert_textbox(pymupdf.Rect(50, 250, 545, 300),
                        "12. McMurray JJ, Packer M, Desai AS, et al. Angiotensin-neprilysin inhibition versus "
                        "enalapril in heart failure. N Engl J Med. 2014;371:993-1004. doi:10.1056/NEJMoa1409077",
                        fontsize=9, fontname="tiro")
    out = Path(path)
    doc.save(str(out))
    return out


if __name__ == "__main__":
    print(make(sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"))
