"""Nhận diện thương hiệu: sinh theme Streamlit (.streamlit/config.toml) và CSS từ mục `branding` trong config.yaml."""
from __future__ import annotations

from .config import ROOT, Config

DEFAULTS = {"name": "MedTrans", "app_title": "MedTrans – Dịch thuật y khoa", "primary_color": "#0B5394",
            "secondary_color": "#F4F7FB", "text_color": "#1D1D1F", "font": "Be Vietnam Pro",
            "logo": "assets/logo.png"}


def brand(cfg: Config) -> dict:
    return {**DEFAULTS, **(cfg.get("branding") or {})}


def write_streamlit_theme(cfg: Config) -> None:
    b = brand(cfg)
    d = ROOT / ".streamlit"
    d.mkdir(exist_ok=True)
    (d / "config.toml").write_text(
        "# Tự sinh từ mục branding trong config.yaml – sửa ở config.yaml rồi chạy lại `python -m medtrans ui`\n"
        "[theme]\n"
        'base = "light"\n'
        f'primaryColor = "{b["primary_color"]}"\n'
        'backgroundColor = "#FFFFFF"\n'
        f'secondaryBackgroundColor = "{b["secondary_color"]}"\n'
        f'textColor = "{b["text_color"]}"\n'
        "\n[server]\n"
        'address = "localhost"\n'
        "maxUploadSize = 2000\n"
        "\n[client]\n"
        'toolbarMode = "minimal"\n'
        "\n[browser]\n"
        "gatherUsageStats = false\n",
        encoding="utf-8")


def css(cfg: Config) -> str:
    b = brand(cfg)
    font = b["font"].replace(" ", "+")
    return f"""
<link href="https://fonts.googleapis.com/css2?family={font}:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  html, body, [class*="css"], .stMarkdown, .stButton button, input, textarea {{
    font-family: '{b["font"]}', 'Segoe UI', Roboto, Arial, sans-serif; }}
  h1, h2, h3 {{ color: {b["primary_color"]}; font-weight: 700; }}
  .brand-bar {{ display:flex; align-items:center; gap:12px; padding:10px 0 14px;
               border-bottom:3px solid {b["primary_color"]}; margin-bottom:12px; }}
  .brand-name {{ font-weight:800; letter-spacing:.06em; color:{b["primary_color"]}; font-size:1.3rem; }}
  .brand-sub {{ color:#5f6368; font-size:.95rem; }}
  .stage {{ padding:4px 10px; border-radius:6px; margin:2px 0; font-size:.92rem; }}
  .stage.done {{ color:#1e7d32; }} .stage.now {{ background:{b["secondary_color"]}; color:{b["primary_color"]};
               font-weight:600; border-left:4px solid {b["primary_color"]}; }} .stage.todo {{ color:#8a8f98; }}
</style>"""


def logo_path(cfg: Config):
    p = ROOT / brand(cfg)["logo"]
    return p if p.exists() else None
