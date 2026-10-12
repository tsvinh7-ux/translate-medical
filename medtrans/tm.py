"""Nhập/xuất bộ nhớ dịch chuẩn TMX (dùng được với SDL Trados, memoQ, OmegaT, Phrase...)."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from .db import Database

TAGS = re.compile(r"</?(?:b|i|sup|sub)>")


def export_tmx(db: Database, path: str | Path, domain: str | None = None, min_quality: int = 0,
               approved_only: bool = False) -> int:
    sql = "SELECT * FROM tm WHERE quality >= ?"
    params: list = [min_quality]
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    if approved_only:
        sql += " AND approved = 1"
    rows = db.query(sql, params)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<tmx version="1.4">',
           f'<header creationtool="MedTrans" creationtoolversion="0.1" datatype="plaintext" segtype="paragraph" '
           f'adminlang="en" srclang="en" o-tmf="medtrans" creationdate="{time.strftime("%Y%m%dT%H%M%SZ")}"/>',
           "<body>"]
    for r in rows:
        out.append(f'<tu><prop type="domain">{escape(r["domain"])}</prop><prop type="quality">{r["quality"]}</prop>'
                   f'<prop type="approved">{r["approved"]}</prop>'
                   f'<tuv xml:lang="en"><seg>{escape(r["src"])}</seg></tuv>'
                   f'<tuv xml:lang="vi"><seg>{escape(r["tgt"])}</seg></tuv></tu>')
    out += ["</body>", "</tmx>"]
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return len(rows)


def import_tmx(db: Database, path: str | Path, domain: str = "general_medicine", quality: int = 95,
               approved: bool = True) -> int:
    """Nhập TMX từ bản dịch người đã duyệt (ví dụ sách đã xuất bản) → nguồn tham khảo/dùng lại."""
    tree = ET.parse(path)
    n = 0
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    for tu in tree.iter("tu"):
        segs = {}
        for tuv in tu.iter("tuv"):
            lang = (tuv.get(xml_lang) or tuv.get("lang") or "").lower()[:2]
            seg = tuv.find("seg")
            if seg is not None:
                segs[lang] = "".join(seg.itertext()).strip()
        if segs.get("en") and segs.get("vi"):
            db.tm_add(segs["en"], segs["vi"], domain, doc_name=Path(path).name, quality=quality, approved=approved)
            n += 1
    return n


def import_bilingual_table(db: Database, path: str | Path, domain: str = "general_medicine", quality: int = 95) -> int:
    """Nhập bảng song ngữ (CSV/XLSX với cột en, vi) – ví dụ câu đã dịch thủ công trước đây."""
    from .glossary import read_rows
    n = 0
    for row in read_rows(path):
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        en = r.get("en") or r.get("english") or r.get("source")
        vi = r.get("vi") or r.get("vietnamese") or r.get("target")
        if en and vi:
            db.tm_add(en, vi, domain, doc_name=Path(path).name, quality=quality, approved=True)
            n += 1
    return n
