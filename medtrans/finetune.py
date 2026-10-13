"""Xuất dữ liệu song ngữ để TINH CHỈNH (fine-tune) model local (Qwen…) bằng LoRA/QLoRA.

Định dạng: JSONL hội thoại (system/user/assistant) – dùng được với Unsloth, LLaMA-Factory, Axolotl, TRL, MLX-LM.
Mỗi mẫu kèm THUẬT NGỮ BẮT BUỘC khớp trong câu → model học dịch theo termbase (điểm yếu lớn nhất của model nhỏ).

NGUỒN DỮ LIỆU (mặc định an toàn): chỉ cặp câu do NGƯỜI dịch/duyệt (origin = human | import).
Điều khoản thương mại của Anthropic (mục D.4) không cho dùng dịch vụ để "train competing AI models" nếu chưa được
chấp thuận → chỉ bật include_machine=True sau khi pháp chế/Anthropic xác nhận.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from .db import Database
from .glossary import TermMatcher

TAGS = re.compile(r"</?(?:b|i|sup|sub)>")
SYSTEM = ("Bạn là dịch giả y khoa Anh → Việt chuẩn xuất bản. Dịch đúng, đủ, đúng trình tự, không thêm, không bớt; "
          "giữ nguyên số liệu, đơn vị, ký hiệu, mã ⟦…⟧; dùng đúng thuật ngữ bắt buộc; văn phong học thuật tự nhiên.")


def export_jsonl(db: Database, out_dir: str | Path, domain: str | None = None, include_machine: bool = False,
                 min_quality: int = 95, val_ratio: float = 0.05, seed: int = 42) -> dict:
    origins = ["human", "import"] + (["machine"] if include_machine else [])
    sql = f"SELECT * FROM tm WHERE approved=1 AND quality>=? AND origin IN ({','.join('?' * len(origins))})"
    params: list = [min_quality, *origins]
    if domain:
        sql += " AND domain=?"
        params.append(domain)
    rows = [dict(r) for r in db.query(sql, params)]
    matcher = TermMatcher(db.terms(status="approved", src_lang=None))
    samples = []
    for r in rows:
        src, tgt = TAGS.sub("", r["src"]).strip(), TAGS.sub("", r["tgt"]).strip()
        if len(src) < 3 or not tgt:
            continue
        terms = matcher.find(src)
        hint = ("Thuật ngữ bắt buộc:\n" + "\n".join(f"- {t['en']} → {t['vi']}" for t in terms) + "\n\n") if terms else ""
        samples.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Chuyên ngành: {r['domain']}\n{hint}Dịch sang tiếng Việt:\n{src}"},
            {"role": "assistant", "content": tgt}],
            "meta": {"origin": r["origin"], "quality": r["quality"], "domain": r["domain"]}})
    random.Random(seed).shuffle(samples)
    n_val = max(1, int(len(samples) * val_ratio)) if len(samples) > 20 else 0
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in (("train.jsonl", samples[n_val:]), ("val.jsonl", samples[:n_val])):
        with open(out / name, "w", encoding="utf-8") as f:
            for s in part:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
    by_origin: dict[str, int] = {}
    for s in samples:
        by_origin[s["meta"]["origin"]] = by_origin.get(s["meta"]["origin"], 0) + 1
    return {"train": len(samples) - n_val, "val": n_val, "by_origin": by_origin, "dir": str(out)}
