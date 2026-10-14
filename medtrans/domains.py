"""GÓI CHUYÊN NGÀNH (domain pack): một lõi chung, mỗi chuyên ngành một gói dữ liệu riêng.

Gói nằm ở data/domains/<key>.yaml: tên, bí danh, chuyên ngành cha, quy ước văn phong, điểm giám khảo phải soát kỹ,
thuật ngữ nền. Khi dịch, hệ thống dùng chuỗi chuyên ngành [gói → cha → general_medicine] cho kho thuật ngữ,
bộ nhớ dịch, quy tắc văn phong đã học – chuyên ngành hẹp kế thừa dữ liệu chung, dữ liệu riêng được ưu tiên.
Thêm chuyên ngành mới = thêm một file YAML, không cần sửa mã.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path

import yaml

from .config import ROOT

DOMAIN_DIR = ROOT / "data" / "domains"
BASE = "general_medicine"


def slug(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").strip().lower()).replace("đ", "d")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_") or BASE


@functools.lru_cache(maxsize=1)
def packs() -> dict[str, dict]:
    out = {}
    for p in sorted(DOMAIN_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        d.setdefault("key", p.stem)
        d.setdefault("parents", [] if d["key"] == BASE else [BASE])
        d.setdefault("terms", [])
        out[d["key"]] = d
    return out


def resolve(name: str | None) -> str:
    """Tên/bí danh bất kỳ ("Nha khoa", "dental", "gây mê") → khoá gói; không có gói → slug của tên."""
    s = slug(name or BASE)
    ps = packs()
    if s in ps:
        return s
    for k, d in ps.items():
        if s in {slug(a) for a in d.get("aliases", [])} or s == slug(d.get("name_vi", "")):
            return k
    return s


def chain(name: str | None) -> list[str]:
    """Chuỗi chuyên ngành dùng khi tra thuật ngữ / bộ nhớ dịch: gói → các gói cha → general_medicine."""
    key = resolve(name)
    out, todo = [], [key]
    while todo:
        k = todo.pop(0)
        if k in out:
            continue
        out.append(k)
        todo.extend(packs().get(k, {}).get("parents", [BASE] if k != BASE else []))
    if BASE not in out:
        out.append(BASE)
    return out


def label(name: str | None) -> str:
    k = resolve(name)
    return packs().get(k, {}).get("name_vi", k)


def prompt_text(name: str | None) -> str:
    """Quy ước văn phong + điểm giám khảo phải soát kỹ của chuỗi chuyên ngành (đưa vào lời dặn cho AI)."""
    parts = []
    for k in reversed(chain(name)):  # chung trước, riêng sau (riêng được ưu tiên)
        d = packs().get(k)
        if not d:
            continue
        if d.get("style"):
            parts.append(f"### Quy ước chuyên ngành: {d.get('name_vi', k)}\n{d['style'].strip()}")
        if d.get("judge_focus"):
            parts.append(f"### Điểm phải soát kỹ ({d.get('name_vi', k)})\n{d['judge_focus'].strip()}")
    return "\n\n".join(parts)


def seed_terms(db, overwrite: bool = False) -> int:
    """Nạp thuật ngữ nền của các gói vào kho thuật ngữ (không ghi đè thuật ngữ đã có / đã duyệt)."""
    n = 0
    for k, d in packs().items():
        for t in d.get("terms", []) or []:
            if not t.get("en") or not t.get("vi"):
                continue
            db.upsert_term(t["en"], t["vi"], k, note=t.get("note", ""), source="domain_pack", overwrite=overwrite,
                           priority=70 if k != BASE else 60)  # thuật ngữ chuyên ngành hẹp được ưu tiên
            n += 1
    return n
