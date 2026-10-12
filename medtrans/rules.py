"""Quy tắc giữ nguyên: bảo vệ bằng mã giữ chỗ và liệt kê token phải giữ nguyên văn."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import ROOT

RULES_PATH = ROOT / "data" / "preserve_rules.yaml"
PLACEHOLDER_RE = re.compile(r"⟦(\w+)⟧")


@dataclass
class Rules:
    protect: list[tuple[str, re.Pattern]]
    must_keep: list[tuple[str, re.Pattern, bool]]   # (name, pattern, only_italic)
    exceptions: set[str]
    units: list[str]
    conventions: list[str]
    raw: dict = field(default_factory=dict)

    def prompt_text(self, number_format: str, drug_style: str, abbreviation_policy: str) -> str:
        lines = ["## NGUYÊN TẮC GIỮ NGUYÊN VÀ QUY ƯỚC"]
        lines.append("1. Mã giữ chỗ dạng ⟦n⟧ (n là số/chữ) phải được chép lại CHÍNH XÁC, đủ số lượng, "
                     "đặt đúng vị trí tương ứng về nghĩa. Không dịch, không thêm, không bớt mã.")
        lines.append("2. Giữ NGUYÊN VĂN (không dịch, không đổi chính tả): " + "; ".join(
            r.get("description", r["name"]) for r in self.raw.get("must_keep", [])) + ".")
        lines.append("3. Ký hiệu đơn vị đo giữ nguyên theo chuẩn quốc tế, không đổi đơn vị, không quy đổi giá trị: "
                     + ", ".join(self.units[:40]) + " ...")
        if number_format == "vi":
            lines.append("4. Định dạng số theo chuẩn Việt Nam: dấu phẩy thập phân (0,5), dấu chấm phân cách hàng nghìn "
                         "(10.000). Giá trị số tuyệt đối không được thay đổi hay làm tròn.")
        else:
            lines.append("4. Giữ nguyên định dạng số như bản gốc. Giá trị số tuyệt đối không được thay đổi.")
        if drug_style == "duoc_thu":
            lines.append("5. Tên hoạt chất viết theo Dược thư Quốc gia Việt Nam (ví dụ: amoxicilin, cefuroxim, "
                         "adrenalin, paracetamol). Tên biệt dược/thương mại giữ nguyên.")
        else:
            lines.append("5. Tên hoạt chất giữ nguyên INN tiếng Anh. Tên biệt dược/thương mại giữ nguyên.")
        if abbreviation_policy == "first_gloss":
            lines.append("6. Chữ viết tắt: lần đầu xuất hiện trong tài liệu ghi 'tên tiếng Việt (VIẾT TẮT)', "
                         "các lần sau giữ chữ viết tắt.")
        else:
            lines.append("6. Chữ viết tắt giữ nguyên.")
        lines.append("7. Quy ước chuyển đổi:")
        lines.extend(f"   - {c}" for c in self.conventions)
        return "\n".join(lines)


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> Rules:
    raw = yaml.safe_load(Path(path or RULES_PATH).read_text(encoding="utf-8")) or {}
    protect = [(r["name"], re.compile(r["pattern"], re.IGNORECASE if r["name"] in ("doi", "url") else 0))
               for r in raw.get("protect", [])]
    must_keep = [(r["name"], re.compile(r["pattern"]), bool(r.get("only_italic")))
                 for r in raw.get("must_keep", [])]
    return Rules(protect=protect, must_keep=must_keep,
                 exceptions={str(x).upper() for x in raw.get("must_keep_exceptions", [])},
                 units=[str(u) for u in raw.get("units", [])],
                 conventions=[str(c) for c in raw.get("conventions", [])], raw=raw)


def protect(text: str, rules: Rules, extra: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Thay các đoạn cần bảo vệ bằng ⟦n⟧. `extra` = mã đã có sẵn (ví dụ công thức inline)."""
    mapping: dict[str, str] = dict(extra or {})
    counter = [len(mapping)]

    def _sub(m: re.Match) -> str:
        counter[0] += 1
        key = f"⟦{counter[0]}⟧"
        mapping[key] = m.group(0)
        return key

    for _, pat in rules.protect:
        # không thay bên trong mã đã có
        parts = re.split(r"(⟦\w+⟧)", text)
        text = "".join(p if PLACEHOLDER_RE.fullmatch(p) else pat.sub(_sub, p) for p in parts)
    return text, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for key, val in mapping.items():
        text = text.replace(key, val)
    return text


def must_keep_tokens(text: str, rules: Rules, italic_spans: list[str] | None = None) -> list[str]:
    """Danh sách token phải xuất hiện nguyên văn trong bản dịch."""
    text_wo_ph = PLACEHOLDER_RE.sub(" ", text)
    words = re.findall(r"[A-Za-z]+", text_wo_ph)
    # Tiêu đề viết HOA toàn bộ → không coi từng từ là viết tắt
    caps_ratio = sum(1 for w in words if w.isupper() and len(w) > 1) / max(1, len(words))
    out: dict[str, None] = {}
    for name, pat, only_italic in rules.must_keep:
        if only_italic:
            for span in italic_spans or []:
                for m in pat.finditer(span):
                    out[m.group(0)] = None
            continue
        if name == "acronym" and caps_ratio > 0.6 and len(words) > 1:
            continue
        for m in pat.finditer(text_wo_ph):
            tok = m.group(0)
            if name == "acronym" and tok.endswith("s") and tok[:-1].isupper():
                tok = tok[:-1]  # ECGs → ECG (tiếng Việt không có số nhiều)
            if tok.upper().rstrip("S") in rules.exceptions or tok.upper() in rules.exceptions:
                continue
            if name == "chemical" and (tok.isupper() and tok.isalpha()):
                continue  # đã thuộc nhóm viết tắt
            out[tok] = None
    return list(out)
