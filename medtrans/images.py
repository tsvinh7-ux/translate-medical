"""Dịch chữ trong hình ảnh/biểu đồ dạng ảnh: OCR → dịch → xoá chữ cũ → vẽ chữ Việt → thay ảnh trong PDF."""
from __future__ import annotations

import io
import logging
import re
import statistics
from dataclasses import dataclass

import pymupdf
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("medtrans.images")


@dataclass
class OcrLine:
    id: str
    text: str
    box: tuple[int, int, int, int]   # pixel x0, y0, x1, y1


def load_image(doc: pymupdf.Document, xref: int) -> Image.Image | None:
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4 or pix.colorspace is None or pix.colorspace.n != 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    except Exception as e:  # ảnh lỗi/định dạng lạ → bỏ qua
        log.warning("Không đọc được ảnh xref=%s: %s", xref, e)
        return None


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def ocr_tesseract(img: Image.Image, prefix: str, lang: str = "eng") -> list[OcrLine]:
    """OCR 2 lượt (chữ rời rạc + bố cục khối) rồi gộp, nhóm từ thành dòng theo hình học."""
    import pytesseract
    scale = 2 if max(img.size) < 1500 else 1
    work = img.resize((img.width * scale, img.height * scale), Image.LANCZOS) if scale > 1 else img
    words: list[tuple[str, tuple[int, int, int, int]]] = []
    for psm in (11, 3):
        data = pytesseract.image_to_data(work, lang=lang, output_type=pytesseract.Output.DICT,
                                         config=f"--psm {psm}")
        for i, w in enumerate(data["text"]):
            if not w.strip() or float(data["conf"][i]) < 55:
                continue
            box = (data["left"][i] // scale, data["top"][i] // scale,
                   (data["left"][i] + data["width"][i]) // scale, (data["top"][i] + data["height"][i]) // scale)
            if any(_iou(box, b) > 0.4 for _, b in words):
                continue
            words.append((w.strip(), box))
    # nhóm thành dòng: chồng lấn theo chiều dọc & khoảng cách ngang nhỏ
    words.sort(key=lambda wb: (wb[1][1], wb[1][0]))
    lines_raw: list[list[tuple[str, tuple]]] = []
    for w, b in sorted(words, key=lambda wb: wb[1][0]):
        h = b[3] - b[1]
        target = None
        for ln in lines_raw:
            lb = ln[-1][1]
            v_overlap = min(lb[3], b[3]) - max(lb[1], b[1])
            if v_overlap > 0.5 * min(h, lb[3] - lb[1]) and 0 <= b[0] - lb[2] < 1.5 * max(h, lb[3] - lb[1]):
                target = ln
                break
        if target is None:
            lines_raw.append([(w, b)])
        else:
            target.append((w, b))
    lines: list[OcrLine] = []
    for n, ln in enumerate(sorted(lines_raw, key=lambda l: (l[0][1][1], l[0][1][0]))):
        text = " ".join(w for w, _ in ln)
        if not re.search(r"[A-Za-z]{2,}", text):
            continue
        box = (min(b[0] for _, b in ln), min(b[1] for _, b in ln), max(b[2] for _, b in ln),
               max(b[3] for _, b in ln))
        lines.append(OcrLine(f"{prefix}_l{n}", text, box))
    return lines


def _bg_color(img: Image.Image, box: tuple[int, int, int, int], pad: int = 3) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    W, H = img.size
    px = img.load()
    ring = []
    for x in range(max(0, x0 - pad), min(W, x1 + pad)):
        for y in (max(0, y0 - pad), min(H - 1, y1 + pad)):
            ring.append(px[x, y])
    for y in range(max(0, y0 - pad), min(H, y1 + pad)):
        for x in (max(0, x0 - pad), min(W - 1, x1 + pad)):
            ring.append(px[x, y])
    if not ring:
        return (255, 255, 255)
    return tuple(int(statistics.median(c[i] for c in ring)) for i in range(3))


def _fg_color(img: Image.Image, box, bg) -> tuple[int, int, int]:
    crop = img.crop(box)
    raw = crop.convert("RGB").tobytes()
    pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    far = [p for p in pixels if sum(abs(p[i] - bg[i]) for i in range(3)) > 120]
    if not far:
        return (0, 0, 0) if sum(bg) > 380 else (255, 255, 255)
    return tuple(int(statistics.median(c[i] for c in far)) for i in range(3))


def _fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: str, box_w: int, box_h: int):
    size = max(8, int(box_h * 0.95))
    while size > 7:
        font = ImageFont.truetype(font_path, size)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        if r - l <= box_w * 1.08 and b - t <= box_h * 1.25:
            return font, (l, t, r, b)
        size -= 1
    font = ImageFont.truetype(font_path, 7)
    return font, draw.textbbox((0, 0), text, font=font)


def redraw(img: Image.Image, lines: list[OcrLine], translations: dict[str, str], font_path: str) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for ln in lines:
        vi = translations.get(ln.id)
        if not vi or vi.strip() == ln.text.strip():
            continue
        vi = re.sub(r"</?(?:b|i|sup|sub)>", "", vi)
        x0, y0, x1, y1 = ln.box
        bg = _bg_color(img, ln.box)
        fg = _fg_color(img, ln.box, bg)
        draw.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), fill=bg)
        font, (l, t, r, b) = _fit_font(draw, vi, font_path, x1 - x0, y1 - y0)
        tw = r - l
        cx = x0 + (x1 - x0 - tw) / 2 if tw < (x1 - x0) else x0
        cy = y0 + ((y1 - y0) - (b - t)) / 2 - t
        if tw > (x1 - x0):  # chữ Việt dài hơn: mở rộng nền sang phải
            draw.rectangle((x0 - 2, y0 - 2, x0 + tw + 2, y1 + 2), fill=bg)
        draw.text((cx, cy), vi, font=font, fill=fg)
    return out


def replace_image(page: pymupdf.Page, xref: int, img: Image.Image) -> None:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    page.replace_image(xref, stream=buf.getvalue())
