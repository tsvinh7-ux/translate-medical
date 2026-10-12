"""MedTrans – giao diện web chạy trên máy (localhost).  Khởi động: python -m medtrans ui"""
from __future__ import annotations

import streamlit as st

from medtrans.branding import brand, logo_path
from medtrans.config import load_config
from ui import pages, state
from ui.theme import inject

cfg = load_config()
B = brand(cfg)
st.set_page_config(page_title=B["app_title"], page_icon="🩺", layout="wide", initial_sidebar_state="expanded")
inject(cfg)
state.queue()  # khởi động hàng đợi chạy nền

with st.sidebar:
    lg = logo_path(cfg)
    if lg:
        st.image(str(lg), width=150)
    st.markdown(f"<div class='sb-brand'><div class='n'>{B['name']}</div><div class='t'>{B['app_title']}</div></div>",
                unsafe_allow_html=True)

P = {
    "dashboard": st.Page(pages.dashboard, title="Tổng quan", icon="🏠", url_path="tong-quan", default=True),
    "new": st.Page(pages.new_project, title="Dự án mới", icon="➕", url_path="du-an-moi"),
    "queue": st.Page(pages.queue_page, title="Hàng đợi & tiến độ", icon="⏱️", url_path="hang-doi"),
    "analytics": st.Page(pages.analytics, title="Phân tích tài liệu", icon="📊", url_path="phan-tich"),
    "termbase": st.Page(pages.termbase_page, title="Termbase dự án", icon="🔒", url_path="termbase"),
    "review": st.Page(pages.review_page, title="Duyệt & can thiệp", icon="✍️", url_path="duyet"),
    "calibration": st.Page(pages.calibration_page, title="Hiệu chuẩn", icon="🎯", url_path="hieu-chuan"),
    "glossary": st.Page(pages.glossary_page, title="Kho thuật ngữ", icon="📚", url_path="thuat-ngu"),
    "tm": st.Page(pages.tm_page, title="Bộ nhớ dịch", icon="🧠", url_path="bo-nho-dich"),
    "settings": st.Page(pages.settings_page, title="Cấu hình & hệ thống", icon="⚙️", url_path="cau-hinh"),
}
st.session_state["_pages"] = P
nav = st.navigation({
    "Vận hành": [P["dashboard"], P["new"], P["queue"]],
    "Chất lượng": [P["analytics"], P["termbase"], P["review"], P["calibration"]],
    "Dữ liệu": [P["glossary"], P["tm"]],
    "Hệ thống": [P["settings"]],
})
nav.run()
