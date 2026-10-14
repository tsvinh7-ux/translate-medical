"""Tài nguyên dùng chung của giao diện (CSDL, hàng đợi chạy nền, cấu hình)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

from medtrans.config import ROOT, load_config
from medtrans.db import Database
from medtrans.glossary import import_file
from medtrans.jobs import JobQueue

UPLOADS = ROOT / "workspace" / "uploads"


def cfg():
    return load_config()


@st.cache_resource
def db() -> Database:
    c = load_config()
    d = Database(c.resolve(c.get_path("memory.db_path", "workspace/medtrans.db")))
    if not d.query("SELECT 1 FROM glossary LIMIT 1"):
        import_file(d, ROOT / "data" / "glossary_seed.csv", overwrite=False)
    if not d.query("SELECT 1 FROM glossary WHERE source='domain_pack' LIMIT 1"):
        from medtrans.domains import seed_terms
        seed_terms(d)
    return d


@st.cache_resource
def queue() -> JobQueue:
    c = load_config()
    return JobQueue(None, db(), parallel=int(c.get_path("queue.parallel_jobs", 1)))


def save_upload(f) -> Path:
    """Lưu file tải lên; trùng tên khác nội dung → thêm hậu tố để không ghi đè."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    data = f.getbuffer()
    path = UPLOADS / f.name
    if path.exists() and hashlib.md5(path.read_bytes()).hexdigest() != hashlib.md5(data).hexdigest():
        path = UPLOADS / f"{path.stem}_{hashlib.md5(data).hexdigest()[:6]}{path.suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


def uploaded_files() -> list[Path]:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    return sorted(UPLOADS.glob("*.pdf"), key=lambda p: -p.stat().st_mtime)


def result_of(row: dict) -> dict:
    try:
        return json.loads(row.get("result_json") or "{}")
    except json.JSONDecodeError:
        return {}
