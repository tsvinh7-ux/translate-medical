"""Quản lý thuật ngữ: nhập/xuất CSV, Excel, TBX và tìm thuật ngữ xuất hiện trong đoạn văn."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .db import Database, normalize_text

# Tên cột chấp nhận được (Anh hoặc Việt không dấu) → tên chuẩn
COLUMN_ALIASES = {
    "en": "en", "english": "en", "term": "en", "source": "en", "tieng_anh": "en", "tiếng anh": "en",
    "vi": "vi", "vietnamese": "vi", "target": "vi", "translation": "vi", "tieng_viet": "vi", "tiếng việt": "vi",
    "domain": "domain", "chuyen_nganh": "domain", "chuyên ngành": "domain",
    "category": "category", "loai": "category", "loại": "category",
    "note": "note", "ghi_chu": "note", "ghi chú": "note", "definition": "note",
    "keep_original": "keep_original", "giu_nguyen": "keep_original", "giữ nguyên": "keep_original",
    "gloss_first": "gloss_first", "chu_thich_lan_dau": "gloss_first",
    "case_sensitive": "case_sensitive", "phan_biet_hoa_thuong": "case_sensitive",
    "priority": "priority", "uu_tien": "priority", "ưu tiên": "priority",
    "source_url": "source_url", "nguon": "source_url", "nguồn": "source_url",
    "status": "status",
}
TRUE_VALUES = {"1", "true", "yes", "y", "x", "co", "có", "đúng"}


def _norm_col(c: str) -> str:
    c = (c or "").strip().lower().replace("-", "_")
    return COLUMN_ALIASES.get(c, COLUMN_ALIASES.get(c.replace("_", " "), c))


def _row_to_term(row: dict, default_domain: str) -> dict | None:
    r = {_norm_col(k): (v if v is not None else "") for k, v in row.items()}
    en = str(r.get("en", "")).strip()
    vi = str(r.get("vi", "")).strip()
    if not en:
        return None
    keep = str(r.get("keep_original", "")).strip().lower() in TRUE_VALUES
    if not vi and not keep:
        return None
    try:
        priority = int(float(r.get("priority") or 50))
    except ValueError:
        priority = 50
    return dict(
        en=en, vi=vi, domain=str(r.get("domain") or default_domain).strip() or default_domain,
        category=str(r.get("category", "")).strip(), note=str(r.get("note", "")).strip(),
        keep_original=keep,
        gloss_first=str(r.get("gloss_first", "")).strip().lower() in TRUE_VALUES,
        case_sensitive=str(r.get("case_sensitive", "")).strip().lower() in TRUE_VALUES,
        priority=priority, source_url=str(r.get("source_url", "")).strip(),
        status=str(r.get("status") or "approved").strip() or "approved",
    )


def read_rows(path: str | Path) -> list[dict]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        rows: list[dict] = []
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            header = next(it, None)
            if not header:
                continue
            cols = [str(h or "") for h in header]
            for vals in it:
                rows.append({cols[i]: ("" if v is None else str(v)) for i, v in enumerate(vals) if i < len(cols)})
        return rows
    if suffix == ".tbx":
        return _read_tbx(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def _read_tbx(path: Path) -> list[dict]:
    tree = ET.parse(path)
    rows = []
    for entry in tree.iter():
        if not entry.tag.endswith("termEntry") and not entry.tag.endswith("conceptEntry"):
            continue
        terms: dict[str, str] = {}
        for lang_set in entry:
            lang = next((v for k, v in lang_set.attrib.items() if k.endswith("lang")), "")
            term_el = next((e for e in lang_set.iter() if e.tag.endswith("term")), None)
            if term_el is not None and term_el.text:
                terms[lang.lower()[:2]] = term_el.text.strip()
        if "en" in terms and "vi" in terms:
            rows.append({"en": terms["en"], "vi": terms["vi"]})
    return rows


def import_file(db: Database, path: str | Path, default_domain: str = "general_medicine",
                source: str = "import", overwrite: bool = True) -> int:
    n = 0
    for row in read_rows(path):
        t = _row_to_term(row, default_domain)
        if not t:
            continue
        db.upsert_term(source=source, overwrite=overwrite, **t)
        n += 1
    return n


def export_csv(db: Database, path: str | Path, status: str | None = "approved") -> int:
    rows = db.terms(status=status)
    cols = ["en", "vi", "domain", "category", "note", "keep_original", "gloss_first", "case_sensitive",
            "priority", "source", "source_url", "status"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------- matching
def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


_TOKEN_RE = re.compile(r"[A-Za-z0-9α-ωΑ-Ω]+(?:[-'’][A-Za-z0-9α-ωΑ-Ω]+)*")


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


class TermMatcher:
    """Tìm nhanh thuật ngữ có trong văn bản (n-gram, chịu được số nhiều tiếng Anh)."""

    def __init__(self, terms: Iterable[dict]):
        self.index: dict[tuple[str, ...], dict] = {}
        self.max_len = 1
        for t in terms:  # terms đã sắp theo priority giảm dần → giữ mục đầu tiên
            toks = [w for w, _, _ in _tokens(t["en"])]
            if not toks:
                continue
            if t.get("case_sensitive"):
                key = ("§cs",) + tuple(toks)
            else:
                key = tuple(_singular(w.lower()) for w in toks)
            self.index.setdefault(key, t)
            self.max_len = max(self.max_len, len(toks))

    def find(self, text: str) -> list[dict]:
        toks = _tokens(text)
        lower = [_singular(w.lower()) for w, _, _ in toks]
        raw = [w for w, _, _ in toks]
        found: dict[int, dict] = {}
        i = 0
        while i < len(toks):
            matched = 0
            for n in range(min(self.max_len, len(toks) - i), 0, -1):  # ưu tiên cụm dài nhất
                t = self.index.get(("§cs",) + tuple(raw[i:i + n])) or self.index.get(tuple(lower[i:i + n]))
                if t:
                    found[t["id"]] = t
                    matched = n
                    break
            i += matched or 1
        return list(found.values())


def format_terms_for_prompt(terms: list[dict]) -> str:
    lines = []
    for t in terms:
        if t.get("keep_original"):
            line = f"- {t['en']} → GIỮ NGUYÊN \"{t['vi'] or t['en']}\""
        elif t.get("gloss_first"):
            line = f"- {t['en']} → {t['vi']}  (lần đầu xuất hiện ghi: {t['vi']} ({t['en']}))"
        else:
            line = f"- {t['en']} → {t['vi']}"
        if t.get("note"):
            line += f"  [ghi chú: {t['note']}]"
        lines.append(line)
    return "\n".join(lines)


def vi_contains(haystack: str, needle: str) -> bool:
    """So khớp tiếng Việt không phân biệt hoa thường nhưng giữ dấu."""
    h = unicodedata.normalize("NFC", haystack).lower()
    n = unicodedata.normalize("NFC", needle).lower().strip()
    return bool(n) and n in h


__all__ = ["import_file", "export_csv", "TermMatcher", "format_terms_for_prompt", "vi_contains", "normalize_text"]
