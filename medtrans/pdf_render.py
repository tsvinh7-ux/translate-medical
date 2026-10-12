"""Dựng lại PDF tiếng Việt giữ nguyên bố cục: xoá chữ gốc (giữ nền, hình, đường kẻ) và đặt chữ Việt vào đúng vị trí."""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .pdf_extract import PageInfo, TextBlock

log = logging.getLogger("medtrans.render")

TAG_SPLIT = re.compile(r"(</?(?:b|i|sup|sub)>)")

FONT_CANDIDATES = {
    "serif": [
        ("C:/Windows/Fonts", ["times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"]),
        ("/System/Library/Fonts/Supplemental", ["Times New Roman.ttf", "Times New Roman Bold.ttf",
                                                "Times New Roman Italic.ttf", "Times New Roman Bold Italic.ttf"]),
        ("/usr/share/fonts/truetype/noto", ["NotoSerif-Regular.ttf", "NotoSerif-Bold.ttf", "NotoSerif-Italic.ttf",
                                            "NotoSerif-BoldItalic.ttf"]),
        ("/usr/share/fonts/truetype/dejavu", ["DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf",
                                              "DejaVuSerif-BoldItalic.ttf"]),
    ],
    "sans": [
        ("C:/Windows/Fonts", ["arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"]),
        ("/System/Library/Fonts/Supplemental", ["Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf",
                                                "Arial Bold Italic.ttf"]),
        ("/usr/share/fonts/truetype/noto", ["NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSans-Italic.ttf",
                                            "NotoSans-BoldItalic.ttf"]),
        ("/usr/share/fonts/truetype/dejavu", ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf",
                                              "DejaVuSans-BoldOblique.ttf"]),
    ],
}


@dataclass
class FontSet:
    serif: list[str]   # [regular, bold, italic, bolditalic] (đường dẫn đầy đủ; có thể thiếu biến thể)
    sans: list[str]

    def css(self) -> str:
        rules = []
        for fam, files in (("vserif", self.serif), ("vsans", self.sans)):
            styles = [("normal", "normal"), ("bold", "normal"), ("normal", "italic"), ("bold", "italic")]
            for path, (weight, style) in zip(files, styles):
                if path:
                    rules.append(f"@font-face {{font-family: {fam}; src: url(\"{os.path.basename(path)}\"); "
                                 f"font-weight: {weight}; font-style: {style};}}")
        return "\n".join(rules)

    def archive(self) -> pymupdf.Archive:
        arch = pymupdf.Archive()
        for d in sorted({os.path.dirname(p) for p in self.serif + self.sans if p}):
            arch.add(d)
        return arch


def find_fonts(layout_cfg: dict) -> FontSet:
    def pick(kind: str) -> list[str]:
        custom = layout_cfg.get(f"{kind}_font", "auto")
        if custom and custom != "auto" and Path(custom).exists():
            return [custom, "", "", ""]
        dirs = FONT_CANDIDATES[kind]
        font_dir = layout_cfg.get("font_dir", "auto")
        if font_dir and font_dir != "auto":
            dirs = [(font_dir, files) for _, files in dirs] + dirs
        for d, files in dirs:
            if Path(d, files[0]).exists():
                return [str(Path(d, f)) if Path(d, f).exists() else "" for f in files]
        return []

    serif, sans = pick("serif"), pick("sans")
    if not serif and not sans:
        raise FileNotFoundError("Không tìm thấy font Unicode hỗ trợ tiếng Việt. Hãy khai báo layout.serif_font / "
                                "layout.sans_font trong config.yaml (ví dụ C:/Windows/Fonts/times.ttf).")
    return FontSet(serif or sans, sans or serif)


def to_html(text: str) -> str:
    """Escape văn bản, chỉ giữ lại các thẻ định dạng cho phép."""
    parts = TAG_SPLIT.split(text)
    return "".join(p if TAG_SPLIT.fullmatch(p) else html.escape(p, quote=False) for p in parts)


def _block_css(b: TextBlock, size: float) -> str:
    fam = "vserif" if b.serif else "vsans"
    return (f"font-family: {fam}; font-size: {size:.2f}pt; color: {b.color}; text-align: {b.align}; "
            f"line-height: {b.line_height:.2f}; font-weight: {'bold' if b.bold else 'normal'}; "
            f"font-style: {'italic' if b.italic else 'normal'}; margin: 0; padding: 0;")


def _free_space_below(b: TextBlock, page: PageInfo) -> float:
    """Khoảng trống phía dưới khối (tới khối kế tiếp chồng theo chiều ngang hoặc lề trang)."""
    limit = page.height - 36
    others = [o.bbox for o in page.blocks if o is not b] + list(page.obstacles)
    for ob in others:
        if ob[1] < b.bbox[3] - 0.5:
            continue
        if ob[0] < b.bbox[2] and ob[2] > b.bbox[0]:
            limit = min(limit, ob[1] - 2)
    return max(0.0, limit - b.bbox[3])


def _free_space_sides(b: TextBlock, page: PageInfo) -> tuple[float, float]:
    """Khoảng trống bên trái/phải của khối một dòng (tới khối kế bên hoặc lề trang)."""
    margin_l = min((o.bbox[0] for o in page.blocks), default=36)
    margin_r = page.width - margin_l
    left_lim, right_lim = margin_l, margin_r
    for o in page.blocks:
        if o is b or not (o.bbox[1] < b.bbox[3] - 0.5 and o.bbox[3] > b.bbox[1] + 0.5):
            continue
        if o.bbox[0] >= b.bbox[2] - 0.5:
            right_lim = min(right_lim, o.bbox[0] - 12)
        elif o.bbox[2] <= b.bbox[0] + 0.5:
            left_lim = max(left_lim, o.bbox[2] + 12)
    return max(0.0, b.bbox[0] - left_lim), max(0.0, right_lim - b.bbox[2])


def render(src_pdf: str | Path, out_pdf: str | Path, pages: list[PageInfo], translations: dict[str, str],
           fonts: FontSet, min_scale: float = 0.6, image_replacements: dict[int, object] | None = None) -> dict:
    """translations: block_id → HTML tiếng Việt (đã khôi phục mã giữ chỗ)."""
    doc = pymupdf.open(str(src_pdf))
    css_fonts = fonts.css()
    archive = fonts.archive()
    stats = {"blocks": 0, "shrunk": 0, "overflow": []}
    for p in pages:
        page = doc[p.number]
        todo = [b for b in p.blocks if not b.keep and translations.get(b.id)]
        if not todo:
            continue
        for b in todo:
            for r in b.line_rects:
                rect = pymupdf.Rect(r)
                rect.y0 += 0.4
                rect.y1 -= 0.4
                page.add_redact_annot(rect, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        # chuẩn bị khung chữ cho từng khối
        prepared = []
        for b in todo:
            rect = pymupdf.Rect(b.bbox)
            rect.x1 += 0.5  # bù sai số đo
            if len(b.line_rects) == 1 and b.rotate == 0:
                # khối một dòng (tiêu đề, nhãn): cho phép giãn ngang vào khoảng trống thay vì xuống dòng
                free_l, free_r = _free_space_sides(b, p)
                if b.align == "center":
                    ext = min(free_l, free_r)
                    rect.x0 -= ext
                    rect.x1 += ext
                elif b.align == "right":
                    rect.x0 -= free_l
                else:
                    rect.x1 += free_r
            prepared.append((b, rect, to_html(translations[b.id])))

        # đo tỉ lệ thu nhỏ cần thiết, rồi đồng bộ cỡ chữ cho các khối cùng loại trên trang
        scratch = pymupdf.open()
        sp = scratch.new_page(width=page.rect.width, height=page.rect.height)
        need: dict[str, float] = {}
        for b, rect, body in prepared:
            html_doc = f'<div style="{_block_css(b, b.font_size)}">{body}</div>'
            spare, sc = sp.insert_htmlbox(rect, html_doc, css=css_fonts, archive=archive, scale_low=min_scale,
                                          rotate=b.rotate)
            sc = sc if spare >= 0 else min_scale
            if sc < 0.98 and b.rotate == 0:
                # ưu tiên dùng khoảng trắng phía dưới trước khi thu nhỏ chữ
                below = min(_free_space_below(b, p), rect.height)
                if below > 2:
                    tall = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + below)
                    spare2, sc2 = sp.insert_htmlbox(tall, html_doc, css=css_fonts, archive=archive,
                                                    scale_low=min_scale)
                    if spare2 >= 0 and sc2 > sc:
                        rect.y1 = tall.y1 if sc2 < 0.999 else rect.y1 + (below - spare2)
                        sc = sc2
            need[b.id] = sc
        scratch.close()
        group_scale: dict[tuple, float] = {}
        for b, _, _ in prepared:
            key = (b.role, round(b.font_size))
            group_scale[key] = min(group_scale.get(key, 1.0), need[b.id])

        for b, rect, body in prepared:
            size = b.font_size * group_scale[(b.role, round(b.font_size))]
            html_doc = f'<div style="{_block_css(b, size)}">{body}</div>'
            spare, scale = page.insert_htmlbox(rect, html_doc, css=css_fonts, archive=archive,
                                               scale_low=min_scale, rotate=b.rotate)
            if spare < 0:
                # không vừa: nới xuống khoảng trống phía dưới rồi cho phép thu nhỏ thêm
                rect.y1 += _free_space_below(b, p)
                spare, scale = page.insert_htmlbox(rect, html_doc, css=css_fonts, archive=archive,
                                                   scale_low=0, rotate=b.rotate)
                stats["overflow"].append({"block": b.id, "page": p.number + 1, "scale": round(scale, 2)})
            if size * scale < b.font_size * 0.999:
                stats["shrunk"] += 1
            stats["blocks"] += 1
    for xref, (page_no, img) in (image_replacements or {}).items():
        from .images import replace_image
        try:
            replace_image(doc[page_no], xref, img)
        except Exception as e:
            log.warning("Không thay được ảnh xref=%s: %s", xref, e)
    doc.subset_fonts()
    doc.save(str(out_pdf), garbage=3, deflate=True)
    doc.close()
    return stats
