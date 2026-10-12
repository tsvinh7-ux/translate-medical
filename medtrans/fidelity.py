"""Chế tài TRUNG THÀNH: dịch đúng, dịch đủ, đúng trình tự, không thêm, không bớt.

Cơ chế:
  1. Máy tách đoạn nguồn thành các câu ĐÁNH SỐ (không phụ thuộc AI).
  2. Kiểm toán viên AI độc lập phải ánh xạ TỪNG câu số → đoạn tương ứng trong bản dịch, kèm phán quyết
     (ok | partial | altered | omitted), và liệt kê phần bản dịch KHÔNG có trong bản gốc (additions).
  3. Máy cưỡng chế:
       - câu số nào không được ánh xạ → coi như BỊ BỎ SÓT (AI không thể "lờ" câu);
       - omitted/altered → lỗi critical; partial/addition → lỗi major;
       - vị trí các đoạn ánh xạ trong bản dịch phải tăng dần (đúng trình tự) → sai trình tự = lỗi major.
     Lỗi được đưa vào vòng chấm MQM: buộc dịch lại, không thể được chứng nhận khi còn lỗi.
"""
from __future__ import annotations

import re

from .rules import PLACEHOLDER_RE

ABBREV = r"(?:e\.g|i\.e|et al|etc|vs|Fig|Figs|Tab|No|Nos|Dr|Mr|Mrs|Ms|Prof|approx|ca|cf|Vol|pp|Eq|Ref|St|Inc|Ltd|Jr|Sr|" \
         r"[A-Z])"
_TAGS = re.compile(r"</?(?:b|i|sup|sub)>")


def split_sentences(text: str) -> list[str]:
    """Tách câu (tiếng Anh/Latin) – an toàn với viết tắt thường gặp, số thập phân, mã giữ chỗ."""
    t = re.sub(r"\s+", " ", _TAGS.sub("", text)).strip()
    if not t:
        return []
    protected = re.sub(r"\b(" + ABBREV + r")\.(?=\s)", lambda m: m.group(1) + "∯", t)
    parts = [p.replace("∯", ".").strip() for p in re.split(r"(?<=[.!?])[\"”’)\]]?\s+(?=[\"“(\[]?[A-Z0-9⟦])",
                                                            protected)]
    return [p for p in parts if re.search(r"\w", p)]


def split_sentences_vi(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", _TAGS.sub("", text)).strip()
    if not t:
        return []
    protected = re.sub(r"\b(và cs|v\.v|tr|TS|ThS|BS|PGS|GS|[A-ZĐ])\.(?=\s)", lambda m: m.group(1) + "∯", t)
    parts = [p.replace("∯", ".").strip()
             for p in re.split(r"(?<=[.!?])[\"”’)\]]?\s+(?=[\"“(\[]?[A-ZÀ-ỸĐ0-9⟦])", protected)]
    return [p for p in parts if re.search(r"\w", p)]


def numbered(src: str) -> list[dict]:
    return [{"n": i + 1, "text": s} for i, s in enumerate(split_sentences(src))]


def enforce(unit_src: str, unit_tgt: str, result: dict) -> list[dict]:
    """Chuyển kết quả kiểm toán thành lỗi MQM, có cưỡng chế bằng máy."""
    expected = numbered(unit_src)
    got = {int(s.get("n", 0)): s for s in result.get("sentences", []) if str(s.get("n", "")).isdigit()
           or isinstance(s.get("n"), int)}
    errors: list[dict] = []
    positions: list[tuple[int, int]] = []
    plain_tgt = _TAGS.sub("", unit_tgt)
    for sent in expected:
        n = sent["n"]
        r = got.get(n)
        verdict = (r or {}).get("verdict", "omitted")
        span = ((r or {}).get("target_span") or "").strip()
        if r is None:
            verdict = "omitted"
        if verdict in ("omitted", "altered"):
            errors.append({"category": "accuracy_omission" if verdict == "omitted" else "accuracy_mistranslation",
                           "severity": "critical", "judge": "fidelity", "source_span": sent["text"][:200],
                           "target_span": span[:200],
                           "explanation": f"Câu {n} {'bị bỏ sót' if verdict == 'omitted' else 'bị đổi nghĩa'}"
                                          f"{': ' + r.get('note', '') if r and r.get('note') else ''}",
                           "fix": f"Dịch đầy đủ, đúng nghĩa câu {n}: {sent['text'][:200]}"})
        elif verdict == "partial":
            errors.append({"category": "accuracy_omission", "severity": "major", "judge": "fidelity",
                           "source_span": sent["text"][:200], "target_span": span[:200],
                           "explanation": f"Câu {n} dịch thiếu ý: {(r or {}).get('note', '')}",
                           "fix": f"Bổ sung phần còn thiếu của câu {n}"})
        if span and verdict != "omitted":
            key = PLACEHOLDER_RE.sub("", span)[:40].strip()
            pos = plain_tgt.find(key) if key else -1
            if pos >= 0:
                positions.append((n, pos))
    for a in result.get("additions", []) or []:
        if a and a.strip():
            errors.append({"category": "accuracy_addition", "severity": "major", "judge": "fidelity",
                           "source_span": "", "target_span": a[:200],
                           "explanation": "Bản dịch có nội dung không có trong bản gốc", "fix": "Bỏ phần thêm vào"})
    # trình tự: các câu phải xuất hiện theo thứ tự bản gốc
    for (n1, p1), (n2, p2) in zip(positions, positions[1:]):
        if p2 < p1:
            errors.append({"category": "accuracy_mistranslation", "severity": "major", "judge": "fidelity",
                           "source_span": f"câu {n1} → {n2}", "target_span": "",
                           "explanation": f"Sai trình tự: câu {n2} đứng trước câu {n1} trong bản dịch",
                           "fix": "Giữ đúng trình tự các câu như bản gốc"})
            break
    return errors
