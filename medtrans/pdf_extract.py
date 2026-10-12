"""Trích xuất nội dung PDF: khối văn bản (kèm định dạng, vai trò, thứ tự đọc), công thức, hình ảnh."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .languages import EN, LangProfile

MATH_FONT_HINTS = ("CMMI", "CMSY", "CMEX", "MSAM", "MSBM", "SYMBOL", "MTEXTRA", "MT EXTRA", "CAMBRIAMATH",
                   "CAMBRIA MATH", "STIXMATH", "LMMATH", "EUCLID", "MATHEMATICALPI", "RSFS", "ESINT", "WASY",
                   "MATH")
SERIF_HINTS = ("TIMES", "SERIF", "MINION", "GEORGIA", "GARAMOND", "CAMBRIA", "PALATINO", "BOOKMAN", "ROMAN",
               "CENTURY", "BASKERVILLE", "CHARTER", "UTOPIA", "NIMBUSROM", "CMR", "LMROMAN", "SABON", "STIX")
SENT_END_RE = re.compile(r"[.!?:;)\]”\"']\s*$")
ALLOWED_TAGS = ("b", "i", "sup", "sub")


@dataclass
class TextBlock:
    id: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str                       # văn bản có thẻ inline <b><i><sup><sub> và mã ⟦Mn⟧ cho công thức
    plain: str                      # văn bản thuần (không thẻ)
    role: str = "body"              # heading | body | caption | label | header_footer | reference | math
    font_size: float = 10.0
    bold: bool = False
    italic: bool = False
    serif: bool = True
    color: str = "#000000"
    align: str = "left"             # left | center | right | justify
    line_height: float = 1.2
    rotate: int = 0
    keep: bool = False              # True = giữ nguyên (công thức, tài liệu tham khảo)
    math_map: dict[str, str] = field(default_factory=dict)
    italic_spans: list[str] = field(default_factory=list)
    line_rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    chain_next: str | None = None   # id khối tiếp nối câu (qua cột/trang)
    chain_prev: str | None = None
    scanned: bool = False           # khối lấy từ OCR trang scan


@dataclass
class ImageItem:
    id: str
    page: int
    xref: int
    bbox: tuple[float, float, float, float]
    width: int
    height: int


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    blocks: list[TextBlock]
    images: list[ImageItem]
    obstacles: list[tuple[float, float, float, float]] = field(default_factory=list)  # hình, khung vẽ
    scanned: bool = False


def _is_math_font(name: str) -> bool:
    n = name.upper().replace("-", "").replace("_", "")
    return any(h.replace(" ", "") in n for h in MATH_FONT_HINTS)


def _color_hex(c: int) -> str:
    return f"#{(c >> 16) & 255:02x}{(c >> 8) & 255:02x}{c & 255:02x}"


def _span_style(span: dict, base_size: float, baseline: float) -> tuple[bool, bool, str]:
    flags = span.get("flags", 0)
    bold = bool(flags & 16) or "BOLD" in span.get("font", "").upper() or "BLACK" in span.get("font", "").upper()
    italic = bool(flags & 2) or any(k in span.get("font", "").upper() for k in ("ITALIC", "OBLIQUE"))
    pos = ""
    size = span.get("size", base_size)
    if flags & 1:
        pos = "sup"
    elif size < base_size * 0.85:
        oy = span.get("origin", (0, baseline))[1]
        if oy < baseline - size * 0.2:
            pos = "sup"
        elif oy > baseline + size * 0.1:
            pos = "sub"
    return bold, italic, pos


def _wrap(text: str, bold: bool, italic: bool, pos: str) -> str:
    if pos:
        text = f"<{pos}>{text}</{pos}>"
    if italic:
        text = f"<i>{text}</i>"
    if bold:
        text = f"<b>{text}</b>"
    return text


def _build_block(raw: dict, page_no: int, idx: int, page_w: float, page_h: float) -> TextBlock | None:
    lines = [ln for ln in raw.get("lines", []) if any(s.get("text", "").strip() for s in ln.get("spans", []))]
    if not lines:
        return None
    all_spans = [s for ln in lines for s in ln["spans"] if s.get("text", "")]
    chars = sum(len(s["text"].strip()) for s in all_spans) or 1
    # cỡ chữ & định dạng chủ đạo (theo số ký tự)
    size_weight: dict[float, int] = {}
    bold_chars = italic_chars = math_chars = serif_chars = 0
    color_weight: dict[int, int] = {}
    for s in all_spans:
        n = len(s["text"].strip())
        size_weight[round(s["size"], 1)] = size_weight.get(round(s["size"], 1), 0) + n
        flags = s.get("flags", 0)
        fname = s.get("font", "")
        if flags & 16 or "BOLD" in fname.upper():
            bold_chars += n
        if flags & 2 or "ITALIC" in fname.upper() or "OBLIQUE" in fname.upper():
            italic_chars += n
        if _is_math_font(fname):
            math_chars += n
        if flags & 4 or any(h in fname.upper() for h in SERIF_HINTS):
            serif_chars += n
        color_weight[s.get("color", 0)] = color_weight.get(s.get("color", 0), 0) + n
    font_size = max(size_weight, key=size_weight.get)
    block_bold = bold_chars / chars > 0.8
    block_italic = italic_chars / chars > 0.8

    math_map: dict[str, str] = {}
    italic_spans: list[str] = []
    parts: list[str] = []
    plain_parts: list[str] = []
    line_rects = []
    prev_line_text = ""
    for li, ln in enumerate(lines):
        line_rects.append(tuple(ln["bbox"]))
        sizes = [s["size"] for s in ln["spans"] if s["text"].strip()]
        base = max(sizes) if sizes else font_size
        baseline = max((s["origin"][1] for s in ln["spans"] if abs(s["size"] - base) < 0.01), default=ln["bbox"][3])
        line_html: list[str] = []
        line_plain: list[str] = []
        cur = None  # (bold, italic, pos, is_math)
        buf = ""

        def flush():
            nonlocal buf, cur
            if not buf:
                return
            b, it, pos, is_math = cur
            if is_math and buf.strip():
                key = f"⟦M{len(math_map) + 1}⟧"
                math_map[key] = _wrap(buf, b and not block_bold, it and not block_italic, pos)
                line_html.append(key)
            else:
                if it and not block_italic and buf.strip():
                    italic_spans.append(buf.strip())
                line_html.append(_wrap(buf, b and not block_bold, it and not block_italic, pos))
            buf = ""

        for s in ln["spans"]:
            t = s.get("text", "")
            if not t:
                continue
            b, it, pos = _span_style(s, base, baseline)
            style = (b, it, pos, _is_math_font(s.get("font", "")) and bool(t.strip()))
            if style != cur:
                flush()
                cur = style
            buf += t
            line_plain.append(t)
        flush()
        lt = "".join(line_html).strip()
        lp = "".join(line_plain).strip()
        if li > 0:
            # nối dòng: bỏ gạch nối cuối dòng nếu từ bị ngắt
            if prev_line_text.endswith("-") and lp[:1].islower() and len(prev_line_text) > 1 \
                    and prev_line_text[-2].isalpha():
                parts[-1] = parts[-1][:-1]
                plain_parts[-1] = plain_parts[-1][:-1]
            else:
                parts.append(" ")
                plain_parts.append(" ")
        parts.append(lt)
        plain_parts.append(lp)
        prev_line_text = lp
    text = re.sub(r"\s+", " ", "".join(parts)).strip()
    plain = re.sub(r"\s+", " ", "".join(plain_parts)).strip()
    # gộp thẻ liền kề: </b><b> → ''
    for tag in ALLOWED_TAGS:
        text = re.sub(rf"</{tag}>(\s*)<{tag}>", r"\1", text)

    bbox = tuple(raw["bbox"])
    # căn lề & giãn dòng
    lefts = [r[0] for r in line_rects]
    rights = [r[2] for r in line_rects]
    width = bbox[2] - bbox[0]
    align = "left"
    if len(line_rects) >= 3 and statistics.pstdev(rights[:-1]) < 2 and statistics.pstdev(lefts) < 2:
        align = "justify"
    elif len(line_rects) >= 1 and width < page_w * 0.8:
        centers = [(r[0] + r[2]) / 2 for r in line_rects]
        if statistics.pstdev(lefts) > 3 and statistics.pstdev(centers) < 2:
            align = "center"
        elif len(line_rects) >= 2 and statistics.pstdev(rights) < 1.5 and statistics.pstdev(lefts) > 3:
            align = "right"
    line_height = 1.2
    if len(line_rects) >= 2:
        gaps = [line_rects[i + 1][1] - line_rects[i][1] for i in range(len(line_rects) - 1)]
        gaps = [g for g in gaps if g > 0]
        if gaps:
            line_height = max(1.0, min(2.0, statistics.median(gaps) / font_size))

    d = lines[0].get("dir", (1, 0))
    rotate = 0
    if abs(d[0]) < 0.1:
        rotate = 90 if d[1] < 0 else 270

    blk = TextBlock(
        id=f"p{page_no}_b{idx}", page=page_no, bbox=bbox, text=text, plain=plain, font_size=font_size,
        bold=block_bold, italic=block_italic, serif=serif_chars / chars > 0.5,
        color=_color_hex(max(color_weight, key=color_weight.get)), align=align, line_height=line_height,
        rotate=rotate, math_map=math_map, italic_spans=italic_spans, line_rects=line_rects)

    alpha_words = re.findall(r"[A-Za-z]{3,}", re.sub(r"⟦M\d+⟧", " ", plain))
    if math_chars / chars > 0.5 or (not alpha_words and re.search(r"[=+×÷∑∫√≤≥]", plain)):
        blk.role, blk.keep = "math", True
    elif not alpha_words:
        blk.keep = True  # chỉ số / ký hiệu → không cần dịch
        blk.role = "label"
    return blk


def _reading_order(blocks: list[TextBlock], page_w: float) -> list[TextBlock]:
    """Thứ tự đọc có xét bố cục nhiều cột: khối không có khối song song ở cột bên kia = khối "toàn dòng",
    chia trang thành các dải; trong mỗi dải đọc hết cột trái rồi tới cột phải."""
    mid = page_w / 2

    def side(b: TextBlock) -> str:
        if b.bbox[0] < mid - 5 and b.bbox[2] > mid + 5:
            return "span"
        return "L" if (b.bbox[0] + b.bbox[2]) / 2 < mid else "R"

    def has_neighbour(b: TextBlock) -> bool:
        other = "R" if side(b) == "L" else "L"
        return any(side(o) == other and o.bbox[1] < b.bbox[3] - 1 and o.bbox[3] > b.bbox[1] + 1
                   for o in blocks if o is not b)

    def is_full(b: TextBlock) -> bool:
        s = side(b)
        if s == "span":
            return True
        if has_neighbour(b):
            return False
        # đoạn tiếp nối ngay dưới một đoạn thuộc cột (cùng lề trái, khoảng cách nhỏ) → vẫn thuộc cột đó
        for o in blocks:
            if o is b or side(o) != s:
                continue
            gap = b.bbox[1] - o.bbox[3]
            if -1 <= gap < max(1.6 * b.font_size, 6) and abs(o.bbox[0] - b.bbox[0]) < 6 and has_neighbour(o):
                return False
        return True

    ordered: list[TextBlock] = []
    band: list[TextBlock] = []

    def flush() -> None:
        ordered.extend(sorted([b for b in band if side(b) == "L"], key=lambda b: b.bbox[1]))
        ordered.extend(sorted([b for b in band if side(b) == "R"], key=lambda b: b.bbox[1]))
        band.clear()

    for b in sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        if is_full(b):
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def extract(pdf_path: str | Path, min_image_px: int = 120, lang: LangProfile = EN, ocr_scans: bool = True,
            scan_dpi: int = 300, page_numbers: set[int] | None = None) -> list[PageInfo]:
    from . import scan
    doc = pymupdf.open(str(pdf_path))
    pages: list[PageInfo] = []
    sizes_all: list[float] = []
    warned = False
    for pno, page in enumerate(doc):
        if page_numbers is not None and pno not in page_numbers:
            continue
        w, h = page.rect.width, page.rect.height
        blocks = []
        scanned = ocr_scans and scan.is_scanned(page)
        if scanned:
            if scan.tesseract_available():
                blocks = scan.page_blocks(page, pno, lang.tesseract, scan_dpi)
            elif not warned:
                warned = True
                import logging
                logging.getLogger("medtrans").warning(
                    "Phát hiện trang scan nhưng chưa cài Tesseract OCR – các trang scan sẽ không được dịch.")
        else:
            raw = page.get_text("dict")
            for i, rb in enumerate(raw["blocks"]):
                if rb.get("type") != 0:
                    continue
                b = _build_block(rb, pno, i, w, h)
                if b:
                    blocks.append(b)
        for b in blocks:
            sizes_all.extend([b.font_size] * max(1, len(b.plain) // 20))
        images = []
        page_area = w * h
        for k, info in enumerate(page.get_image_info(xrefs=True)):
            xref = info.get("xref", 0)
            if not xref or info.get("width", 0) < min_image_px or info.get("height", 0) < min_image_px:
                continue
            r = pymupdf.Rect(info["bbox"])
            if scanned and r.width * r.height > page_area * 0.4:
                continue  # chính là ảnh scan của trang – chữ đã được OCR theo đoạn
            images.append(ImageItem(id=f"p{pno}_img{k}", page=pno, xref=xref, bbox=tuple(info["bbox"]),
                                    width=info["width"], height=info["height"]))
        obstacles = [tuple(i["bbox"]) for i in page.get_image_info()]
        try:
            obstacles += [tuple(r) for r in page.cluster_drawings() if r.width * r.height > 400]
        except Exception:
            pass
        if scanned:
            obstacles = [o for o in obstacles if (o[2] - o[0]) * (o[3] - o[1]) < page_area * 0.4]
        pages.append(PageInfo(pno, w, h, _reading_order(blocks, w), images, obstacles, scanned=scanned))
    doc.close()

    body_size = statistics.median(sizes_all) if sizes_all else 10.0
    in_refs = False
    ordered = [b for p in pages for b in p.blocks]
    for p in pages:
        for b in p.blocks:
            if b.role == "math" or (b.keep and b.role == "label"):
                continue
            top, bottom = b.bbox[1], b.bbox[3]
            if lang.references.match(b.plain):
                b.role = "heading"
                in_refs = True
                continue
            if lang.caption.match(b.plain):
                b.role = "caption"
            elif (b.font_size > body_size * 1.15 or (b.bold and len(b.plain) < 150)) and len(b.plain) < 250:
                b.role = "heading"
                if b.scanned:
                    b.bold = True  # trang scan không nhận được độ đậm → tiêu đề in đậm theo thông lệ
                if in_refs and b.font_size >= body_size * 1.15:
                    in_refs = False  # sang chương/mục mới
            elif (bottom < p.height * 0.07 or top > p.height * 0.93) and len(b.plain) < 150:
                b.role = "header_footer"
            elif len(b.plain) < 40 and b.font_size < body_size * 0.95:
                b.role = "label"
            if in_refs and b.role in ("body", "label"):
                b.role, b.keep = "reference", True

    # nối câu bị ngắt qua cột / trang
    body = [b for b in ordered if b.role == "body" and not b.keep]
    for a, nxt in zip(body, body[1:]):
        if not SENT_END_RE.search(a.plain) and nxt.plain[:1].islower() and nxt.page - a.page <= 1:
            a.chain_next, nxt.chain_prev = nxt.id, a.id
    return pages
