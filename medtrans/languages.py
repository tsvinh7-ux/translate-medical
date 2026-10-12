"""Hồ sơ ngôn ngữ nguồn (dịch sang tiếng Việt).

Mỗi ngôn ngữ nguồn khai báo những gì phụ thuộc ngôn ngữ: mã OCR, cách viết số, từ phủ định, từ thông dụng
(để phát hiện sót chữ chưa dịch), mẫu nhận diện chú thích hình/bảng và mục tài liệu tham khảo.
Hiện hoàn thiện: Anh → Việt. Thêm ngôn ngữ mới: xem docs/THEM_NGON_NGU.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LangProfile:
    code: str                    # mã ISO 639-1: en, fr, de...
    name_vi: str                 # "tiếng Anh" – dùng trong prompt
    short_vi: str                # "Anh" – dùng trong "Anh → Việt"
    tesseract: str               # mã ngôn ngữ Tesseract OCR: eng, fra, deu...
    number_style: str            # "dot_decimal" (1,000.5) | "comma_decimal" (1.000,5 hoặc 1 000,5)
    negation: re.Pattern         # từ phủ định / chống chỉ định
    stopwords: frozenset[str]    # từ thông dụng → còn trong bản dịch = sót chưa dịch
    caption: re.Pattern          # dòng mở đầu chú thích hình/bảng
    references: re.Pattern       # tiêu đề mục tài liệu tham khảo
    tokenizer: str = "latin"     # latin | cjk (dự phòng cho tiếng Trung/Nhật/Hàn)
    ready: bool = True           # False = mới khung, chưa kiểm thử chất lượng


EN = LangProfile(
    code="en", name_vi="tiếng Anh", short_vi="Anh", tesseract="eng", number_style="dot_decimal",
    negation=re.compile(r"\b(not|no(?!\.\s*\d)|never|without|contraindicat\w*|avoid\w*|neither|nor|cannot|"
                        r"\w+n't|unless)\b", re.I),
    stopwords=frozenset({
        "the", "of", "and", "with", "is", "are", "was", "were", "for", "from", "which", "that", "this", "these",
        "those", "should", "would", "been", "have", "has", "into", "their", "there", "when", "while", "patients",
        "patient", "also", "other", "such", "between", "after", "before", "however", "because", "without",
        "within", "during", "about", "more", "most", "each", "only", "used", "using", "treatment", "disease",
        "therapy", "increased", "decreased", "or", "by", "be", "it", "at", "as", "not", "will", "can", "may",
        "than", "but", "if"}),
    caption=re.compile(r"^\s*(Figure|Fig\.|Table|Box|Chart|Graph|Algorithm|Panel|Exhibit)\s*[\dA-Z]", re.I),
    references=re.compile(r"^\s*(\d+\.?\s*)?(References|Bibliography|Works Cited|Literature Cited|"
                          r"Suggested Reading|Further Reading)\s*$", re.I),
)

PROFILES: dict[str, LangProfile] = {"en": EN}

# từ tiếng Việt viết không dấu trùng từ thông dụng của ngôn ngữ nguồn → không coi là sót
VI_AMBIGUOUS = frozenset({"can", "may", "than", "an", "do", "to", "in", "the", "be", "it", "at", "as", "but", "or",
                          "by", "if", "not", "la", "de", "des", "con", "tu", "se", "me", "da", "ban", "bo"})


def get_profile(code: str | None) -> LangProfile:
    code = (code or "en").lower()
    if code not in PROFILES:
        raise ValueError(f"Chưa hỗ trợ ngôn ngữ nguồn '{code}'. Hiện có: {', '.join(PROFILES)}. "
                         "Xem docs/THEM_NGON_NGU.md để thêm.")
    return PROFILES[code]


def localize(text: str, lang: LangProfile) -> str:
    """Thay {SRC} / {SRC_SHORT} trong prompt bằng tên ngôn ngữ nguồn."""
    return text.replace("{SRC_SHORT}", lang.short_vi).replace("{SRC}", lang.name_vi)
