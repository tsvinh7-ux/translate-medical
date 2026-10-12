"""Hệ thống thiết kế giao diện: màu, chữ, thẻ KPI, nhãn trạng thái, thanh công đoạn, biểu đồ thanh."""
from __future__ import annotations

import html

import streamlit as st

from medtrans.branding import brand

STATUS = {  # trạng thái → (nhãn, biểu tượng, lớp màu) – luôn có chữ + biểu tượng, không chỉ dựa vào màu
    "queued": ("Chờ", "○", "neutral"), "running": ("Đang chạy", "▶", "info"), "paused": ("Tạm dừng", "❚❚", "warn"),
    "awaiting_termbase": ("Chờ khoá termbase", "◆", "accent"), "done": ("Hoàn tất", "✓", "good"),
    "failed": ("Lỗi", "✕", "bad"), "cancelled": ("Đã huỷ", "—", "neutral"),
    "certified": ("Đạt chuẩn", "✓", "good"), "needs_review": ("Còn lỗi nặng", "!", "bad"),
    "tm": ("Từ bộ nhớ dịch", "↺", "info"), "draft": ("Bản thô", "✎", "warn"),
}

STAGES = [(0.02, "Phân tích bố cục & OCR"), (0.025, "Đọc tổng quan"), (0.05, "Chuẩn bị thuật ngữ toàn văn"),
          (0.8, "Dịch · Hiệu đính · Biên tập · Hội đồng MQM · Kiểm toán trung thành"),
          (0.84, "Chữ trong hình"), (0.88, "Biên tập toàn văn"), (0.9, "Dàn trang"),
          (0.95, "Đọc morat & sửa morat"), (1.0, "Làm giàu dữ liệu & báo cáo")]


def inject(cfg) -> dict:
    b = brand(cfg)
    p, sec, txt = b["primary_color"], b["secondary_color"], b["text_color"]
    font = b["font"]
    st.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family={font.replace(' ', '+')}:wght@400;500;600;700;800&display=swap"
 rel="stylesheet">
<style>
:root {{ --p:{p}; --p-soft:{sec}; --ink:{txt}; --ink-2:#4a4f57; --muted:#6b7280; --line:#e6e8ec; --card:#ffffff;
        --good:#1a7f37; --good-bg:#e8f5ec; --warn:#9a6700; --warn-bg:#fff4d6; --bad:#c62828; --bad-bg:#fdecec;
        --info:#0b57d0; --info-bg:#e8f0fe; --accent:#6d28d9; --accent-bg:#f1eafe; --neutral:#4b5563;
        --neutral-bg:#f1f3f5; }}
html, body, .stApp, .stMarkdown, p, li, label, input, textarea, select, button, h1, h2, h3, h4,
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"], [data-baseweb] {{
  font-family:'{font}', 'Segoe UI', Roboto, Arial, sans-serif; }}
[data-testid="stIconMaterial"], .material-symbols-rounded, span[class*="material"] {{
  font-family:'Material Symbols Rounded' !important; }}
.block-container {{ padding-top:1.6rem; max-width:1320px; }}
h1, h2, h3 {{ color:var(--ink); letter-spacing:-.01em; }}
h1 {{ font-weight:800; font-size:1.65rem; }} h2 {{ font-weight:700; font-size:1.25rem; }}
h3 {{ font-weight:700; font-size:1.05rem; }}
[data-testid="stSidebar"] {{ background:linear-gradient(180deg, var(--p-soft) 0%, #ffffff 100%);
  border-right:1px solid var(--line); }}
.sb-brand {{ padding:4px 2px 14px; border-bottom:1px solid var(--line); margin-bottom:6px; }}
.sb-brand .n {{ font-weight:800; font-size:1.35rem; color:var(--p); letter-spacing:.08em; }}
.sb-brand .t {{ font-size:.8rem; color:var(--muted); }}
.page-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:6px; }}
.page-head .sub {{ color:var(--muted); font-size:.92rem; margin-top:-6px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin:8px 0 18px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); }}
.kpi .l {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:600; }}
.kpi .v {{ font-size:1.6rem; font-weight:800; color:var(--ink); line-height:1.2; margin-top:4px; }}
.kpi .h {{ font-size:.78rem; color:var(--muted); margin-top:2px; }}
.kpi.accent {{ border-top:3px solid var(--p); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:12px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); }}
.card h4 {{ margin:0 0 6px; font-size:1rem; }}
.muted {{ color:var(--muted); font-size:.86rem; }}
.pill {{ display:inline-flex; align-items:center; gap:6px; font-size:.76rem; font-weight:600; padding:3px 10px;
  border-radius:999px; white-space:nowrap; }}
.pill.good {{ color:var(--good); background:var(--good-bg); }} .pill.warn {{ color:var(--warn); background:var(--warn-bg); }}
.pill.bad {{ color:var(--bad); background:var(--bad-bg); }} .pill.info {{ color:var(--info); background:var(--info-bg); }}
.pill.accent {{ color:var(--accent); background:var(--accent-bg); }}
.pill.neutral {{ color:var(--neutral); background:var(--neutral-bg); }}
.stages {{ display:flex; flex-direction:column; gap:2px; margin:6px 0; }}
.stg {{ font-size:.86rem; padding:5px 10px; border-radius:8px; color:var(--muted); }}
.stg.done {{ color:var(--good); }} .stg.now {{ background:var(--p-soft); color:var(--p); font-weight:700;
  border-left:3px solid var(--p); }}
.bars, .tbl {{ width:100%; font-size:.88rem; border:none !important; }}
.bars {{ border-collapse:separate; border-spacing:0 6px; }}
.bars tr, .bars td {{ border:none !important; background:transparent !important; }}
.bars td {{ padding:2px 8px; vertical-align:middle; }}
.tbl {{ border-collapse:collapse; }} .tbl tr, .tbl td, .tbl th {{ border:none !important; }}
.tbl th {{ text-align:left; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
  font-weight:600; padding:6px 10px; border-bottom:1px solid var(--line) !important; }}
.tbl td {{ padding:9px 10px; border-bottom:1px solid #f0f1f3 !important; vertical-align:middle; }}
.tbl td.num {{ text-align:right; font-variant-numeric:tabular-nums; }} .bars td.num {{ text-align:right; color:var(--ink-2);
  font-variant-numeric:tabular-nums; white-space:nowrap; }}
.bar-bg {{ background:#f1f3f5; border-radius:4px; height:12px; width:100%; min-width:80px; }}
.bar {{ background:var(--p); height:12px; border-radius:0 4px 4px 0; }}
.prof {{ border:1px solid var(--line); border-radius:14px; padding:14px 16px; background:#fff; height:100%; }}
.prof.sel {{ border:2px solid var(--p); box-shadow:0 0 0 3px var(--p-soft); }}
.prof .t {{ font-weight:800; font-size:1.02rem; }} .prof .d {{ color:var(--muted); font-size:.82rem; min-height:54px; }}
.prof .row {{ display:flex; flex-direction:column; font-size:.84rem; padding:6px 0; border-bottom:1px dashed var(--line); }}
.prof .row span {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; }}
.prof .row b {{ font-variant-numeric:tabular-nums; font-weight:700; color:var(--ink); }}
div[data-testid="stProgress"] > div > div > div > div {{ background-color:var(--p); }}
.stButton > button[kind="primary"] {{ background:var(--p); border-color:var(--p); font-weight:600; }}
.stButton > button {{ border-radius:10px; }}
[data-testid="stExpander"] {{ border-radius:12px; border:1px solid var(--line); }}
footer {{ visibility:hidden; }}
</style>""", unsafe_allow_html=True)
    return b


def esc(x) -> str:
    return html.escape(str(x))


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="page-head"><div><h1>{esc(title)}</h1>'
                + (f'<div class="sub">{esc(subtitle)}</div>' if subtitle else "") + "</div></div>",
                unsafe_allow_html=True)


def kpis(items: list[tuple], accent_first: bool = False) -> None:
    """items: (nhãn, giá trị, gợi ý)."""
    cells = []
    for i, it in enumerate(items):
        label, value = it[0], it[1]
        hint = it[2] if len(it) > 2 else ""
        cls = "kpi accent" if accent_first and i == 0 else "kpi"
        cells.append(f'<div class="{cls}"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div>'
                     + (f'<div class="h">{esc(hint)}</div>' if hint else "") + "</div>")
    st.markdown(f'<div class="kpis">{"".join(cells)}</div>', unsafe_allow_html=True)


def pill(status: str) -> str:
    label, icon, cls = STATUS.get(status, (status, "•", "neutral"))
    return f'<span class="pill {cls}">{icon} {esc(label)}</span>'


def stages_html(frac: float | None) -> str:
    """frac=None → chỉ hiển thị sơ đồ quy trình (không tô trạng thái)."""
    out, prev = [], 0.0
    for end, name in STAGES:
        if frac is None:
            cls = ""
        else:
            cls = "done" if frac >= end else ("now" if frac >= prev else "")
        icon = "✓" if cls == "done" else ("▶" if cls == "now" else "○")
        out.append(f'<div class="stg {cls}">{icon} {esc(name)}</div>')
        prev = end
    return f'<div class="stages">{"".join(out)}</div>'


def bars(rows: list[tuple[str, float, str]], unit: str = "") -> None:
    """Biểu đồ thanh ngang một chuỗi (một màu): (nhãn, giá trị, chú thích phải)."""
    mx = max((r[1] for r in rows), default=0) or 1
    trs = []
    for label, val, right in rows:
        w = 100 * val / mx
        trs.append(f'<tr title="{esc(label)}: {val:,.0f}{unit}"><td style="width:30%">{esc(label)}</td>'
                   f'<td style="width:50%"><div class="bar-bg"><div class="bar" style="width:{w:.1f}%"></div></div>'
                   f'</td><td class="num">{esc(right)}</td></tr>')
    st.markdown(f'<table class="bars">{"".join(trs)}</table>', unsafe_allow_html=True)


def fmt_int(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")
