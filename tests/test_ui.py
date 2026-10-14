"""Kiểm thử giao diện: mọi màn hình mở được, không lỗi."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDTRANS_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("MEDTRANS_PROVIDER", "mock")
    monkeypatch.chdir(ROOT)


@pytest.mark.parametrize("page", ["tong-quan", "du-an-moi", "hang-doi", "phan-tich", "termbase", "duyet",
                                  "hieu-chuan", "thuat-ngu", "bo-nho-dich", "chuyen-nganh", "cau-hinh"])
def test_every_page_renders(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    import ui.pages as pages
    fn = {"tong-quan": pages.dashboard, "du-an-moi": pages.new_project, "hang-doi": pages.queue_page,
          "phan-tich": pages.analytics, "termbase": pages.termbase_page, "duyet": pages.review_page,
          "hieu-chuan": pages.calibration_page, "thuat-ngu": pages.glossary_page, "bo-nho-dich": pages.tm_page, "chuyen-nganh": pages.knowledge_page,
          "cau-hinh": pages.settings_page}[page]
    script = f"""
import streamlit as st
from ui.theme import inject
from ui import state, pages
from medtrans.config import load_config
inject(load_config())
st.session_state["_pages"] = {{}}
pages.{fn.__name__}()
"""
    at2 = AppTest.from_string(script, default_timeout=60)
    at2.run()
    assert not at2.exception, [e.value for e in at2.exception]
