"""Kiểm soát VĂN PHONG tiếng Việt: phát hiện "văn dịch máy / văn AI", câu quá dài, bị động dày, sáo ngữ…

- Mức đoạn: trả về Issue(severity="style") → đưa vào bước biên tập ngôn ngữ để sửa (không chặn chứng nhận).
- Mức tài liệu: chỉ số dễ đọc (độ dài câu, % câu dài, mật độ lỗi văn phong / 1.000 từ, mẫu hay gặp nhất)
  → đưa vào phiếu kiểm định và cổng phát hành.
Quy tắc nằm trong data/style_vi.yaml – nhà xuất bản tự sửa, không cần sửa mã.
"""
from __future__ import annotations

import functools
import re
from collections import Counter
from pathlib import Path

import yaml

from .config import ROOT
from .rules import PLACEHOLDER_RE

STYLE_FILE = ROOT / "data" / "style_vi.yaml"
_TAGS = re.compile(r"</?(?:b|i|sup|sub)>")


@functools.lru_cache(maxsize=4)
def load_style(path: str | None = None) -> dict:
    p = Path(path) if path else STYLE_FILE
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    pats = []
    for it in data.get("patterns", []) or []:
        pats.append({**it, "re": re.compile(it["regex"], re.I | re.M), "min_count": int(it.get("min_count", 1))})
    return {"house_rules": data.get("house_rules", []) or [], "patterns": pats,
            "long_sentence_words": int(data.get("long_sentence_words", 50))}


def house_rules_text(style: dict | None = None) -> str:
    rules = (style or load_style())["house_rules"]
    if not rules:
        return ""
    return "## VĂN PHONG NHÀ XUẤT BẢN\n" + "\n".join(f"- {r}" for r in rules)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", PLACEHOLDER_RE.sub(" ", _TAGS.sub("", text or "").replace("⟦¶⟧", " "))).strip()


def _sentences(text: str) -> list[str]:
    from .fidelity import split_sentences_vi
    return split_sentences_vi(text)


def segment_issues(tgt: str, style: dict | None = None) -> list:
    """Các vấn đề văn phong của một đoạn dịch (severity='style')."""
    from .verify import Issue
    st = style or load_style()
    text = _plain(tgt)
    if not text:
        return []
    out = []
    for p in st["patterns"]:
        hits = p["re"].findall(text)
        if len(hits) >= p["min_count"]:
            ex = hits[0] if isinstance(hits[0], str) else " ".join(hits[0])
            out.append(Issue("style", f"style_{p['id']}", f"Văn phong: {p['message']} (vd: “{ex.strip()[:40]}”)"))
    limit = st["long_sentence_words"]
    for s in _sentences(text):
        n = len(s.split())
        if n > limit:
            out.append(Issue("style", "style_long", f"Văn phong: câu dài {n} từ – cân nhắc tách câu nếu không "
                                                    f"đổi nghĩa (“{s[:50]}…”)"))
            break
    return out


def document_metrics(texts: list[str], style: dict | None = None) -> dict:
    """Chỉ số văn phong toàn tài liệu."""
    st = style or load_style()
    words = sents = long_s = 0
    flags: Counter = Counter()
    for t in texts:
        text = _plain(t)
        if not text:
            continue
        ss = _sentences(text)
        sents += len(ss)
        words += len(text.split())
        long_s += sum(1 for s in ss if len(s.split()) > st["long_sentence_words"])
        for p in st["patterns"]:
            n = len(p["re"].findall(text))
            if n >= p["min_count"]:
                flags[p["id"]] += 1
    total = sum(flags.values())
    msg = {p["id"]: p["message"] for p in st["patterns"]}
    return {"words": words, "sentences": sents,
            "avg_sentence_words": round(words / sents, 1) if sents else 0,
            "long_sentence_percent": round(100 * long_s / sents, 1) if sents else 0,
            "style_flags": total, "style_flags_per_1000_words": round(1000 * total / words, 2) if words else 0,
            "top": [{"id": k, "count": c, "message": msg.get(k, k)} for k, c in flags.most_common(6)]}
