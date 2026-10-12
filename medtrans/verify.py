"""Tự đối chiếu bản dịch với bản gốc bằng quy tắc (không tốn token).

Kiểm tra: số liệu, cặp số–đơn vị (liều lượng), mã giữ chỗ, token phải giữ nguyên, thuật ngữ bắt buộc,
phủ định, sót tiếng Anh, độ dài bất thường, thẻ định dạng.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .glossary import vi_contains
from .rules import PLACEHOLDER_RE, Rules, must_keep_tokens

TAG_RE = re.compile(r"</?(?:b|i|sup|sub)>")
EN_NEG = re.compile(r"\b(not|no(?!\.\s*\d)|never|without|contraindicat\w*|avoid\w*|neither|nor|cannot|"
                    r"\w+n't|unless)\b", re.I)
VI_NEG = re.compile(r"(không|chưa|chẳng|chống chỉ định|tránh|cấm|ngoại trừ|trừ khi|thiếu|vắng|chớ|"
                    r"đừng|ngưng|ngừng|âm tính|loại trừ|thất bại|phi |bất )", re.I)
EN_STOP = {"the", "of", "and", "with", "is", "are", "was", "were", "for", "from", "which", "that", "this",
           "these", "those", "should", "would", "been", "have", "has", "into", "their", "there", "when",
           "while", "patients", "patient", "also", "other", "such", "between", "after", "before", "however",
           "because", "without", "within", "during", "about", "more", "most", "each", "only", "used",
           "using", "treatment", "disease", "therapy", "increased", "decreased", "or", "by", "be", "it",
           "at", "as", "not", "will", "can", "may", "than", "but", "if"}
# từ tiếng Việt viết không dấu trùng tiếng Anh → bỏ qua
VI_AMBIGUOUS = {"can", "may", "than", "an", "do", "to", "in", "the", "be", "it", "at", "as", "but", "or", "by", "if",
                "not"}


@dataclass
class Issue:
    severity: str   # error | warning
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def strip_tags(s: str) -> str:
    return TAG_RE.sub("", s)


# ------------------------------------------------------------------ numbers
_NUM_EN = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?![\w])")
_NUM_VI = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d.])|\d+,\d+|\d+\.\d+|\d+)(?![\w])")


def _canon(value: str) -> str:
    v = value.lstrip("0") or "0"
    if v.startswith("."):
        v = "0" + v
    if "." in v:
        v = v.rstrip("0").rstrip(".") or "0"
    return v


def numbers_en(text: str) -> list[str]:
    out = []
    for m in _NUM_EN.finditer(text):
        out.append(_canon(m.group(1).replace(",", "")))
    return out


def numbers_vi(text: str, number_format: str) -> list[str]:
    if number_format != "vi":
        return numbers_en(text)
    out = []
    for m in _NUM_VI.finditer(text):
        tok = m.group(1)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", tok):
            tok = tok.replace(".", "").replace(",", ".")
        elif "," in tok:
            tok = tok.replace(",", ".")
        # "0.5" (AI giữ kiểu Anh) → vẫn hiểu là thập phân
        out.append(_canon(tok))
    return out


def _clean_for_numbers(text: str) -> str:
    text = PLACEHOLDER_RE.sub(" ", strip_tags(text))
    text = re.sub(r"\[\d[\d\s,–\-]*\]", " ", text)  # trích dẫn [1,4] kiểm tra riêng
    # bỏ số dính chữ (HbA1c, BRCA1, CD4, T2N0M0) – được kiểm tra ở nhóm token giữ nguyên
    text = re.sub(r"\b[A-Za-zÀ-ỹα-ω]+\d[\w\-]*|\b\d+[A-Za-zÀ-ỹ]+\w*", " ", text)
    return text


def _unit_pairs(text: str, units: list[str], parse) -> Counter:
    unit_alt = "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    pat = re.compile(rf"(\d[\d.,]*)\s?({unit_alt})(?![A-Za-zÀ-ỹ])")
    out: Counter = Counter()
    for m in pat.finditer(strip_tags(text)):
        nums = parse(m.group(1))
        if nums:
            unit = m.group(2).replace("μ", "µ").replace("mcg", "µg").replace("ml", "mL").replace("dl", "dL")
            out[(nums[-1], unit)] += 1
    return out


def check(src: str, tgt: str, *, rules: Rules, number_format: str = "vi", placeholders: dict | None = None,
          glossary_terms: list[dict] | None = None, italic_spans: list[str] | None = None,
          role: str = "body") -> list[Issue]:
    issues: list[Issue] = []
    if not tgt or not tgt.strip():
        return [Issue("error", "empty", "Bản dịch rỗng")]

    # 1. mã giữ chỗ
    for key in (placeholders or {}):
        n = tgt.count(key)
        if n != 1:
            issues.append(Issue("error", "placeholder", f"Mã {key} xuất hiện {n} lần (phải đúng 1 lần)"))
    stray = [k for k in set(PLACEHOLDER_RE.findall(tgt)) if f"⟦{k}⟧" not in (placeholders or {})]
    if stray:
        issues.append(Issue("error", "placeholder", f"Mã lạ trong bản dịch: {stray}"))

    # 2. số liệu
    src_nums = Counter(numbers_en(_clean_for_numbers(src)))
    tgt_nums = Counter(numbers_vi(_clean_for_numbers(tgt), number_format))
    missing = src_nums - tgt_nums
    extra = tgt_nums - src_nums
    if missing:
        issues.append(Issue("error", "number_missing",
                            f"Số liệu có trong bản gốc nhưng thiếu/sai trong bản dịch: {sorted(missing.elements())}"))
    if extra:
        issues.append(Issue("warning", "number_extra",
                            f"Số liệu xuất hiện thêm trong bản dịch: {sorted(extra.elements())}"))

    # 3. cặp số – đơn vị (liều lượng)
    sp = _unit_pairs(src, rules.units, lambda s: numbers_en(s))
    tp = _unit_pairs(tgt, rules.units, lambda s: numbers_vi(s, number_format))
    lost = sp - tp
    if lost:
        issues.append(Issue("error", "unit_mismatch",
                            "Cặp số–đơn vị không khớp: " + ", ".join(f"{v} {u}" for (v, u) in lost.elements())))

    # 4. token phải giữ nguyên
    keep = must_keep_tokens(src, rules, italic_spans)
    plain_tgt = strip_tags(tgt)
    miss_keep = [k for k in keep if k not in plain_tgt]
    if miss_keep:
        issues.append(Issue("warning", "keep_missing", f"Ký hiệu/viết tắt cần giữ nguyên bị thiếu: {miss_keep}"))

    # 5. thuật ngữ bắt buộc
    for t in glossary_terms or []:
        if t.get("keep_original"):
            if t["en"].lower() not in plain_tgt.lower():
                issues.append(Issue("warning", "glossary", f"Thuật ngữ '{t['en']}' phải giữ nguyên"))
        elif not vi_contains(plain_tgt, t["vi"]):
            issues.append(Issue("warning", "glossary",
                                f"Chưa dùng thuật ngữ chuẩn: '{t['en']}' → '{t['vi']}'"))

    # 6. phủ định
    plain_src = strip_tags(src)
    if EN_NEG.search(plain_src) and not VI_NEG.search(plain_tgt):
        issues.append(Issue("error", "negation", "Bản gốc có ý phủ định/chống chỉ định nhưng bản dịch không thể hiện"))

    # 7. sót tiếng Anh
    toks = re.findall(r"[A-Za-z]+", PLACEHOLDER_RE.sub(" ", plain_tgt))
    keep_lower = {k.lower() for k in keep}
    eng = [w for w in toks if w.lower() in EN_STOP and w.lower() not in VI_AMBIGUOUS and w.lower() not in keep_lower]
    if len(eng) >= 2 and len(eng) / max(1, len(toks)) > 0.03:
        issues.append(Issue("error", "untranslated", f"Có thể còn sót tiếng Anh: {eng[:8]}"))

    # 8. độ dài bất thường
    ls, lt = len(plain_src), len(plain_tgt)
    if ls > 60 and (lt < ls * 0.5 or lt > ls * 2.6):
        issues.append(Issue("warning", "length", f"Độ dài bất thường (gốc {ls} ký tự, dịch {lt} ký tự) – "
                                                  "nghi thiếu/thừa ý"))

    # 9. thẻ định dạng
    for tag in ("b", "i", "sup", "sub"):
        if tgt.count(f"<{tag}>") != tgt.count(f"</{tag}>"):
            issues.append(Issue("warning", "tags", f"Thẻ <{tag}> không cân bằng"))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
