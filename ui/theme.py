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
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin:8px 0 18px; }}
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
/* ---------- Dự án mới: wizard 4 bước ---------- */
.stepper {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin:6px 0 8px; }}
.stepper .s {{ display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:12px; background:#fff;
  border:1px solid var(--line); font-size:.86rem; color:var(--muted); font-weight:600; }}
.stepper .s .n {{ width:26px; height:26px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  background:var(--neutral-bg); color:var(--neutral); font-weight:800; font-size:.8rem; flex:none; }}
.stepper .s.done {{ color:var(--ink); }} .stepper .s.done .n {{ background:var(--good-bg); color:var(--good); }}
.stepper .s.now {{ border-color:var(--p); color:var(--ink); box-shadow:0 0 0 3px var(--p-soft); }}
.stepper .s.now .n {{ background:var(--p); color:#fff; }}
.step {{ display:flex; align-items:center; gap:12px; margin:26px 0 12px; }}
.step .num {{ width:34px; height:34px; border-radius:10px; background:var(--p); color:#fff; font-weight:800;
  display:flex; align-items:center; justify-content:center; flex:none; }}
.step .st {{ font-weight:800; font-size:1.14rem; color:var(--ink); line-height:1.2; }}
.step .ss {{ color:var(--muted); font-size:.86rem; }}
.eng {{ border:1px solid var(--line); border-radius:16px; padding:18px 20px; background:#fff; position:relative;
  box-shadow:0 1px 2px rgba(16,24,40,.04); }}
.eng.sel {{ border:2px solid var(--p); box-shadow:0 0 0 4px var(--p-soft), 0 10px 26px rgba(16,24,40,.08); }}
.eng .hd {{ display:flex; align-items:center; gap:14px; padding-right:96px; }}
.eng .ic {{ font-size:1.5rem; width:48px; height:48px; border-radius:12px; background:var(--p-soft);
  display:flex; align-items:center; justify-content:center; flex:none; }}
.eng .t {{ font-weight:800; font-size:1.16rem; color:var(--ink); }} .eng .tg {{ color:var(--muted); font-size:.85rem; }}
.eng .flag {{ position:absolute; top:16px; right:16px; }}
.eng .roles {{ margin:14px 0 6px; display:grid; grid-template-columns:1fr auto; gap:7px 14px; font-size:.84rem; }}
.eng .roles span {{ color:var(--ink-2); }} .eng .roles b {{ text-align:right; font-weight:600; color:var(--ink); }}
.eng .stt {{ border-top:1px dashed var(--line); padding-top:10px; margin-top:10px; font-size:.82rem;
  display:flex; flex-direction:column; gap:6px; }}
.eng .stt div {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
.eng .stt span {{ color:var(--muted); }}
.eng .pc {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:12px; font-size:.79rem; }}
.eng .pc div {{ border-radius:10px; padding:7px 10px; }}
.eng .pc .pro {{ background:var(--good-bg); color:var(--good); }} .eng .pc .con {{ background:var(--warn-bg); color:var(--warn); }}
.scope {{ border:1px solid var(--line); border-radius:14px; padding:14px 14px 12px; background:#fff;
  display:flex; flex-direction:column; gap:9px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
.scope.sel {{ border:2px solid var(--p); box-shadow:0 0 0 3px var(--p-soft), 0 8px 20px rgba(16,24,40,.07); }}
.scope .lvl {{ display:flex; justify-content:space-between; align-items:center; font-size:.68rem; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); font-weight:700; }}
.scope .t {{ font-weight:800; font-size:1rem; line-height:1.25; min-height:2.5em; color:var(--ink); }}
.scope .d {{ color:var(--muted); font-size:.79rem; min-height:128px; }}
.scope .chk {{ display:flex; flex-direction:column; gap:2px; font-size:.8rem; }}
.scope .chk .on {{ color:var(--good); font-weight:600; }} .scope .chk .off {{ color:#b8bec7; }}
.scope .est {{ display:flex; flex-direction:column; gap:4px; background:var(--neutral-bg); border-radius:10px;
  padding:8px 10px; }}
.scope .est div {{ display:flex; justify-content:space-between; align-items:baseline; gap:6px; }}
.scope .est span {{ font-size:.64rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); white-space:nowrap; }}
.scope .est b {{ font-size:.86rem; font-variant-numeric:tabular-nums; color:var(--ink); white-space:nowrap; }}
.scope .dl {{ font-size:.76rem; color:var(--ink-2); min-height:2.3em; }}
.mx {{ width:100%; border-collapse:collapse; font-size:.86rem; }}
.mx tr, .mx td, .mx th {{ border:none !important; }}
.mx th {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:600;
  padding:6px 10px; text-align:left; border-bottom:1px solid var(--line) !important; }}
.mx th.g {{ text-align:center; color:var(--ink); font-size:.74rem; border-bottom:2px solid var(--p) !important; }}
.mx td {{ padding:9px 10px; border-bottom:1px solid #f0f1f3 !important; }}
.mx td:first-child {{ white-space:nowrap; }}
.mx td.c, .mx th.c {{ text-align:center; }} .mx td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.mx .on {{ color:var(--good); font-weight:800; }} .mx .off {{ color:#c4c9d0; }}
.mx tr.sel td {{ background:var(--p-soft); }} .mx td.hl {{ color:var(--p); font-weight:800; }}
.flow .r {{ display:grid; grid-template-columns:28px 1fr auto; align-items:center; gap:10px; padding:8px 2px;
  border-bottom:1px solid #f0f1f3; font-size:.88rem; color:var(--ink); }}
.flow .r:last-child {{ border-bottom:none; }}
.flow .i {{ width:24px; height:24px; border-radius:50%; background:var(--p-soft); color:var(--p); font-weight:800;
  font-size:.74rem; display:flex; align-items:center; justify-content:center; }}
.who {{ font-size:.74rem; font-weight:600; padding:3px 10px; border-radius:999px; white-space:nowrap; }}
.who.local {{ color:var(--good); background:var(--good-bg); }} .who.api {{ color:var(--info); background:var(--info-bg); }}
.who.machine {{ color:var(--neutral); background:var(--neutral-bg); }} .who.human {{ color:var(--accent); background:var(--accent-bg); }}
.sum {{ background:linear-gradient(160deg, var(--p) 0%, color-mix(in srgb, var(--p) 62%, #000) 100%); color:#fff;
  border-radius:18px; padding:22px 24px; box-shadow:0 12px 32px rgba(16,24,40,.18); }}
.sum .hd {{ font-weight:800; font-size:1.06rem; padding-bottom:12px; margin-bottom:14px;
  border-bottom:1px solid rgba(255,255,255,.22); }}
.sum .hd small {{ display:block; font-weight:500; opacity:.8; font-size:.8rem; margin-top:2px; }}
.sum .k {{ font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; opacity:.78; font-weight:600; }}
.sum .v {{ font-size:1.75rem; font-weight:800; line-height:1.15; margin:2px 0 14px; font-variant-numeric:tabular-nums; }}
.sum .v.sm {{ font-size:1.02rem; font-weight:700; }}
.sum .note {{ font-size:.76rem; opacity:.82; border-top:1px solid rgba(255,255,255,.22); padding-top:10px; }}
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
