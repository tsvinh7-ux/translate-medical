"""PDF scan (trang là ảnh chụp): OCR theo đoạn văn → khối chữ có toạ độ trên trang.

Mục tiêu: dịch ĐÚNG và ĐỦ, giữ định dạng cơ bản (vị trí đoạn, cỡ chữ ước lượng, tiêu đề, căn lề).
Văn bản OCR sau đó được Claude đối chiếu với ảnh để sửa lỗi nhận dạng (translator._fix_ocr) trước khi dịch.
"""
from __future__ import annotations

import io
import logging
import re
import statistics

import os

import pymupdf
from PIL import Image

# OCR chạy song song nhiều tiến trình → mỗi tiến trình Tesseract chỉ dùng 1 luồng (tránh tranh chấp CPU)
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

log = logging.getLogger("medtrans.scan")


def is_scanned(page: pymupdf.Page, min_chars: int = 30, min_cover: float = 0.4) -> bool:
    """Trang gần như không có lớp chữ nhưng có ảnh phủ phần lớn diện tích → coi là trang scan."""
    if len(page.get_text("text").strip()) >= min_chars:
        return False
    area = page.rect.width * page.rect.height
    covered = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        covered += r.width * r.height
    return covered / area >= min_cover


_TESS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract",
]
_TESS_OK: bool | None = None


def tesseract_cmd() -> str | None:
    """Tìm Tesseract: PATH → biến TESSERACT_CMD → thư mục cài đặt mặc định (Windows/macOS/Linux)."""
    import shutil
    for c in [os.environ.get("TESSERACT_CMD", ""), shutil.which("tesseract") or "", *_TESS_PATHS]:
        if c and os.path.isfile(c):
            return c
    return None


def tesseract_available() -> bool:
    global _TESS_OK
    if _TESS_OK is not None:
        return _TESS_OK
    try:
        import pytesseract
        cmd = tesseract_cmd()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        pytesseract.get_tesseract_version()
        _TESS_OK = True
    except Exception:
        _TESS_OK = False
    return _TESS_OK


def render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def ocr_paragraphs(img: Image.Image, lang: str) -> list[dict]:
    """Trả về các đoạn: {text, box(px), lines:[box], line_heights:[px]} theo thứ tự Tesseract."""
    import pytesseract
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 3")
    paras: dict[tuple, dict] = {}
    for i, word in enumerate(data["text"]):
        if not word.strip() or float(data["conf"][i]) < 30:
            continue
        pkey = (data["block_num"][i], data["par_num"][i])
        lkey = data["line_num"][i]
        x0, y0 = data["left"][i], data["top"][i]
        x1, y1 = x0 + data["width"][i], y0 + data["height"][i]
        p = paras.setdefault(pkey, {"lines": {}})
        ln = p["lines"].setdefault(lkey, {"words": [], "box": [x0, y0, x1, y1]})
        ln["words"].append(word)
        b = ln["box"]
        ln["box"] = [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
    # mỗi đoạn = danh sách dòng {text, box}
    groups = [[{"text": " ".join(ln["words"]), "box": ln["box"]} for _, ln in sorted(p["lines"].items())]
              for p in paras.values()]
    groups = _merge_overlapping(groups)
    out = []
    for lines in groups:
        texts: list[str] = []
        for ln in lines:
            t = ln["text"]
            if texts and texts[-1].endswith("-") and t[:1].islower() and len(texts[-1]) > 1 \
                    and texts[-1][-2].isalpha():
                texts[-1] = texts[-1][:-1] + t  # nối từ bị ngắt cuối dòng
            else:
                texts.append(t)
        text = re.sub(r"\s+", " ", " ".join(texts)).strip()
        if not re.search(r"[^\W\d_]{2,}", text):
            continue
        boxes = [ln["box"] for ln in lines]
        out.append({
            "text": text,
            "box": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                    max(b[3] for b in boxes)],
            "lines": boxes,
        })
    return out


def _bbox(lines: list[dict]) -> list[float]:
    return [min(l["box"][0] for l in lines), min(l["box"][1] for l in lines),
            max(l["box"][2] for l in lines), max(l["box"][3] for l in lines)]


def _rows(lines: list[dict]) -> list[dict]:
    """Gộp các mảnh dòng nằm cùng hàng (Tesseract đôi khi cắt dòng căn đều thành nhiều mảnh) và sắp xếp."""
    rows: list[list[dict]] = []
    for ln in sorted(lines, key=lambda l: (l["box"][1], l["box"][0])):
        h = ln["box"][3] - ln["box"][1]
        for r in rows:
            rb = _bbox(r)
            overlap = min(rb[3], ln["box"][3]) - max(rb[1], ln["box"][1])
            if overlap > 0.5 * min(h, rb[3] - rb[1]):
                r.append(ln)
                break
        else:
            rows.append([ln])
    out = []
    for r in sorted(rows, key=lambda r: _bbox(r)[1]):
        r.sort(key=lambda l: l["box"][0])
        out.append({"text": " ".join(l["text"] for l in r), "box": _bbox(r)})
    return out


def _merge_overlapping(groups: list[list[dict]]) -> list[list[dict]]:
    """Gộp các đoạn có khung chồng lấn nhau (cùng một đoạn văn bị Tesseract tách nhầm)."""
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            a = _bbox(groups[i])
            for j in range(i + 1, len(groups)):
                b = _bbox(groups[j])
                ix = min(a[2], b[2]) - max(a[0], b[0])
                iy = min(a[3], b[3]) - max(a[1], b[1])
                if ix > 0 and iy > 0:
                    groups[i] = groups[i] + groups[j]
                    del groups[j]
                    changed = True
                    break
            if changed:
                break
    return [_rows(g) for g in groups]


def page_blocks(page: pymupdf.Page, pno: int, lang: str, dpi: int = 300):
    """OCR một trang scan → list[TextBlock] (toạ độ điểm PDF)."""
    return blocks_from_image(render_page(page, dpi), pno, lang, dpi)


def blocks_from_image(img: Image.Image, pno: int, lang: str, dpi: int = 300):
    """OCR ảnh trang đã render → list[TextBlock]. An toàn khi chạy song song (không dùng đối tượng PyMuPDF)."""
    from .pdf_extract import TextBlock
    k = 72.0 / dpi
    blocks = []
    for i, p in enumerate(ocr_paragraphs(img, lang)):
        lines_pt = [tuple(v * k for v in b) for b in p["lines"]]
        heights = [b[3] - b[1] for b in lines_pt]
        x_height = statistics.median(heights) if heights else 10.0
        font_size = max(5.0, min(48.0, x_height * 0.92))
        line_height = 1.2
        if len(lines_pt) >= 2:
            gaps = [lines_pt[j + 1][1] - lines_pt[j][1] for j in range(len(lines_pt) - 1)]
            gaps = [g for g in gaps if g > 0]
            if gaps:
                line_height = max(1.0, min(2.0, statistics.median(gaps) / font_size))
        lefts = [b[0] for b in lines_pt]
        rights = [b[2] for b in lines_pt]
        align = "left"
        if len(lines_pt) >= 3 and statistics.pstdev(rights[:-1]) < 4 and statistics.pstdev(lefts) < 4:
            align = "justify"
        elif len(lines_pt) >= 1:
            centers = [(b[0] + b[2]) / 2 for b in lines_pt]
            if len(lines_pt) >= 2 and statistics.pstdev(lefts) > 6 and statistics.pstdev(centers) < 4:
                align = "center"
        color = _text_color(img, p["box"])
        text = p["text"].replace("<", "‹").replace(">", "›") if re.search(r"</?(?:b|i|sup|sub)>", p["text"]) \
            else p["text"]
        blocks.append(TextBlock(
            id=f"p{pno}_s{i}", page=pno, bbox=tuple(v * k for v in p["box"]), text=text, plain=p["text"],
            font_size=round(font_size, 1), serif=True, align=align, line_height=line_height,
            line_rects=lines_pt, scanned=True, color=color))
    return blocks


def _text_color(img: Image.Image, box) -> str:
    """Màu chữ ước lượng: trung vị các điểm ảnh khác hẳn màu nền trong khung đoạn."""
    crop = img.crop(tuple(int(v) for v in box)).convert("RGB")
    crop.thumbnail((300, 300))
    raw = crop.tobytes()
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    if not px:
        return "#000000"
    bg = tuple(statistics.median(c[i] for c in px) for i in range(3))
    fg = [c for c in px if sum(abs(c[i] - bg[i]) for i in range(3)) > 150]
    if not fg:
        return "#000000"
    col = tuple(int(statistics.median(c[i] for c in fg)) for i in range(3))
    if max(col) - min(col) < 60:
        return "#000000"  # chữ trung tính (đen/xám do khử răng cưa) → đen thuần cho rõ nét
    return "#%02x%02x%02x" % col


def background_color(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[float, float, float]:
    """Màu nền quanh đoạn chữ (để phủ chữ gốc) – trung vị các điểm ảnh ở viền."""
    clip = pymupdf.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3) & page.rect
    pix = page.get_pixmap(clip=clip, dpi=50, colorspace=pymupdf.csRGB, alpha=False)
    w, h, n = pix.width, pix.height, pix.n
    if w < 2 or h < 2:
        return (1.0, 1.0, 1.0)
    s = pix.samples
    pts = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + \
          [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    cols = [s[(y * w + x) * n:(y * w + x) * n + 3] for x, y in pts]
    return tuple(statistics.median(c[i] for c in cols) / 255 for i in range(3))
