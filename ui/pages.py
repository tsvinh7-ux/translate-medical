"""Các màn hình của ứng dụng."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from medtrans.config import PROFILE_ORDER, ROOT, apply_profile, load_config
from medtrans.languages import PROFILES as LANGS

from . import state
from .theme import bars, esc, fmt_int, kpis, page_header, pill, stages_html


ORIGIN = {"glossary": "Kho chuẩn", "termprep": "AI đề xuất", "web": "Tra cứu web", "termbase": "Đã kiểm tra"}


def _profiles(cfg) -> list[str]:
    return [p for p in PROFILE_ORDER if p in (cfg.get("profiles") or {})]


def _money(lo: float, hi: float) -> str:
    if hi <= 0:
        return "$0"
    if hi < 0.01:
        return "< $0.01"
    return f"${lo:,.0f}–{hi:,.0f}" if hi >= 20 else f"${lo:.2f}–{hi:.2f}"


def _plabel(cfg, name: str) -> str:
    from medtrans import plans
    if plans.is_plan(name):
        return plans.plan_label(name)
    return (cfg.get("profiles") or {}).get(name, {}).get("label", name)


# =====================================================================================  TỔNG QUAN
def dashboard():
    cfg, db, q = state.cfg(), state.db(), state.queue()
    page_header("Tổng quan", "Tình hình vận hành, chất lượng và dữ liệu tích luỹ")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("MEDTRANS_PROVIDER")):
        st.warning("Chưa có Claude API key – vào **Cấu hình & hệ thống** để nhập khoá và kiểm tra hệ thống trước khi "
                   "dịch.")
        if st.session_state.get("_pages", {}).get("settings"):
            st.page_link(st.session_state["_pages"]["settings"], label="Mở Cấu hình & hệ thống", icon="⚙️")
    seg = db.query("SELECT COUNT(*) n, AVG(CASE WHEN score>0 THEN score END) s, "
                   "SUM(status='certified') c, SUM(status='needs_review') r, SUM(length(src)) ch "
                   "FROM segments WHERE kind='text'")[0]
    jobs = q.list(500)
    done = [j for j in jobs if j["status"] == "done"]
    running = [j for j in jobs if j["status"] in ("running", "paused", "queued")]
    cost = 0.0
    for r in db.query("SELECT usage_json FROM jobs WHERE usage_json IS NOT NULL"):
        try:
            cost += json.loads(r["usage_json"]).get("estimated_cost_usd", 0)
        except (TypeError, json.JSONDecodeError):
            pass
    n = seg["n"] or 0
    tm = db.tm_stats()
    terms = db.query("SELECT COUNT(*) n FROM glossary WHERE status='approved'")[0]["n"]
    kpis([("Dự án hoàn tất", fmt_int(len(done)), f"{len(running)} đang chạy/chờ"),
          ("Khối lượng đã dịch", f"{(seg['ch'] or 0) / 3000:,.0f} A4".replace(",", "."), f"{fmt_int(n)} đoạn"),
          ("Điểm MQM trung bình", f"{seg['s'] or 0:.1f}", "thang 100"),
          ("Tỉ lệ đạt chuẩn", f"{100 * (seg['c'] or 0) / n:.0f}%" if n else "—", "tự chứng nhận"),
          ("Còn lỗi nặng", fmt_int(seg["r"] or 0), "đoạn cần xem"),
          ("Kho thuật ngữ", fmt_int(terms), "đã duyệt"),
          ("Bộ nhớ dịch", fmt_int(tm["approved"]), f"/{fmt_int(tm['segments'])} cặp câu đạt chuẩn"),
          ("Chi phí tích luỹ", f"${cost:,.2f}", "ước tính theo token")], accent_first=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader("Công việc gần đây")
        if not jobs:
            st.info("Chưa có công việc nào. Bắt đầu ở mục **Dự án mới**.")
        rows = []
        for j in jobs[:12]:
            rows.append(f"<tr><td>#{j['id']}</td><td>{esc(j['name'])}</td><td>{esc(_plabel(cfg, j['profile']))}</td>"
                        f"<td>{pill(j['status'])}</td><td class='num'>{100 * (j['progress'] or 0):.0f}%</td></tr>")
        if rows:
            st.markdown("<div class='card'><table class='tbl'><tr><th>Mã</th><th>Tài liệu</th><th>Hồ sơ</th>"
                        f"<th>Trạng thái</th><th style='text-align:right'>Tiến độ</th></tr>{''.join(rows)}</table></div>",
                        unsafe_allow_html=True)
    with c2:
        st.subheader("Quy trình xuất bản")
        st.markdown("<div class='card'>" + stages_html(None) + "<div class='muted'>Mỗi công đoạn có điểm lưu; "
                    "có thể tạm dừng / tiếp tục / huỷ ở mục Hàng đợi.</div></div>", unsafe_allow_html=True)


# =====================================================================================  DỰ ÁN MỚI
STEPS = ["Tài liệu", "Phương thức xử lý", "Phạm vi công việc", "Xác nhận & chạy"]


def _stepper(done: int) -> None:
    cells = []
    for i, name in enumerate(STEPS, 1):
        cls = "done" if i <= done else ("now" if i == done + 1 else "")
        cells.append(f"<div class='s {cls}'><div class='n'>{'✓' if cls == 'done' else i}</div>{esc(name)}</div>")
    st.markdown(f"<div class='stepper'>{''.join(cells)}</div>", unsafe_allow_html=True)


def _step(n: int, title: str, sub: str = "") -> None:
    st.markdown(f"<div class='step'><div class='num'>{n}</div><div><div class='st'>{esc(title)}</div>"
                + (f"<div class='ss'>{esc(sub)}</div>" if sub else "") + "</div></div>", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def _hw() -> dict:
    from medtrans.hardware import detect
    return detect()


@st.cache_data(ttl=20, show_spinner=False)
def _server_models(url: str) -> list[str] | None:
    import httpx2
    try:
        r = httpx2.get(url.rstrip("/") + "/models", timeout=1.5, trust_env=False)
        return [m.get("id", "") for m in r.json().get("data", [])]
    except Exception:  # noqa: BLE001
        return None


def _parse_pages(txt: str):
    txt = (txt or "").strip()
    if not txt:
        return None
    a, _, b = txt.partition("-")
    try:
        a, b = int(a), int(b or a)
    except ValueError:
        return "invalid"
    return (min(a, b), max(a, b)) if a > 0 and b > 0 else "invalid"


def _badge(ok: bool | None, yes: str, no: str) -> str:
    if ok is None:
        return "<span class='pill accent'>◆ Chế độ trình diễn</span>"
    return f"<span class='pill {'good' if ok else 'warn'}'>{'✓' if ok else '!'} {esc(yes if ok else no)}</span>"


def _who(name: str) -> str:
    cls = ("machine" if name == "Máy bạn" else "human" if name.startswith("Bạn") else
           "api" if name.startswith("Claude") else "local")
    return f"<span class='who {cls}'>{esc(name)}</span>"


def _unit(sec: float) -> tuple[float, str]:
    if sec < 3600:
        return max(1, round(sec / 60)), "phút"
    if sec < 48 * 3600:
        return round(sec / 3600, 1), "giờ"
    return round(sec / 86400, 1), "ngày"


def _num(x: float) -> str:
    return (f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}").replace(".", ",")


def _trange(est: dict) -> str:
    """Khoảng thời gian gọn: "2–6 phút", "3,5–7,9 giờ", "45 phút – 1,2 giờ"."""
    sec = est["estimated_seconds"]
    (a, ua), (b, ub) = _unit(sec * .7), _unit(sec * 1.6)
    if ua == ub:
        return f"≈ {_num(a)} {ua}" if a == b else f"{_num(a)}–{_num(b)} {ua}"
    return f"{_num(a)} {ua} – {_num(b)} {ub}"


def _scan_inputs(paths, cfg, db, domain, pr, lang) -> list[dict]:
    """Quét & phân tích tài liệu (không gọi API) – lưu đệm theo file + tham số."""
    from medtrans.analysis import analyze
    cache = st.session_state.setdefault("np_scan", {})
    out = []
    for pth in paths:
        key = f"{pth}|{pth.stat().st_mtime}|{domain}|{pr}|{lang}"
        if key not in cache:
            c = load_config()
            c["translation"]["source_lang"] = lang
            cache[key] = analyze(pth, c, db, domain=domain, page_range=pr, with_profiles=True)
        out.append(cache[key])
    return out


def new_project():
    from medtrans import plans
    cfg, db, q = state.cfg(), state.db(), state.queue()
    demo = bool(os.environ.get("MEDTRANS_PROVIDER"))
    ss = st.session_state
    ss.setdefault("np_engine", cfg.get_path("plans.default_engine", "api"))
    ss.setdefault("np_scope", cfg.get_path("plans.default_scope", "publish"))
    page_header("Dự án mới", "Quét tài liệu → chọn phương thức & phạm vi công việc → xem dự toán → đưa vào hàng đợi")
    stepper = st.empty()

    # ---------------------------------------------------------------- 1. TÀI LIỆU
    _step(1, "Tài liệu đầu vào", "PDF gốc (văn bản hoặc scan) – hệ thống quét ngay trên máy, không gọi API")
    with st.container(border=True):
        files = st.file_uploader("Tài liệu PDF (có thể chọn nhiều file)", type=["pdf"], accept_multiple_files=True)
        c1, c2, c3 = st.columns(3)
        lang = c1.selectbox("Ngôn ngữ nguồn → tiếng Việt", list(LANGS),
                            format_func=lambda c: f"{LANGS[c].name_vi.capitalize()} ({c})")
        domain = c2.text_input("Chuyên ngành", cfg.get_path("translation.domain", "general_medicine"),
                               help="cardiology, oncology, pharmacology... Kho thuật ngữ & bộ nhớ dịch lưu theo chuyên ngành")
        pages_txt = c3.text_input("Phạm vi trang (để trống = toàn bộ)", placeholder="ví dụ 1-50")
    pr = _parse_pages(pages_txt)
    if pr == "invalid":
        st.error("Phạm vi trang không hợp lệ – nhập dạng 1-50 hoặc 12.")
    paths = [state.save_upload(f) for f in files] if files else []
    domain = domain.strip() or "general_medicine"
    scans = []
    if paths and pr != "invalid":
        with st.spinner("Đang quét bố cục, đếm từ, đối chiếu bộ nhớ dịch & thuật ngữ..."):
            scans = _scan_inputs(paths, cfg, db, domain, pr, lang)
    counts = None
    if scans:
        tot = lambda k: sum(a["totals"][k] for a in scans)        # noqa: E731
        fil = lambda k: sum(a["file"][k] for a in scans)          # noqa: E731
        counts = {"pages": fil("pages_analyzed"), "chars": tot("chars"), "weighted_chars": tot("weighted_chars"),
                  "scanned": fil("scanned_pages"), "images": fil("images")}
        saving = 100 * (1 - counts["weighted_chars"] / counts["chars"]) if counts["chars"] else 0
        kpis([("Tài liệu", fmt_int(len(scans)), f"{sum(a['file']['size_mb'] for a in scans):.1f} MB"),
              ("Số trang", fmt_int(counts["pages"]), f"{fmt_int(counts['scanned'])} trang scan"),
              ("Quy đổi A4", fmt_int(round(counts["chars"] / 3000)), "3.000 ký tự / trang"),
              ("Từ cần dịch", fmt_int(tot("words")), f"{fmt_int(tot('weighted_words'))} từ quy đổi"),
              ("Tiết kiệm nhờ TM & lặp", f"{saving:.0f}%", "không phải dịch lại"),
              ("Thuật ngữ nhận diện", fmt_int(sum(a["terms"]["unique"] for a in scans)),
               f"{fmt_int(sum(a['terms']['occurrences'] for a in scans))} lần xuất hiện"),
              ("Hình · Công thức", f"{fmt_int(counts['images'])} · {fmt_int(fil('math_blocks'))}", "dịch chữ · giữ nguyên")],
             accent_first=True)
    elif not paths:
        st.markdown("<div class='muted'>Tải tài liệu lên để hệ thống quét và tính dự toán chi phí – thời gian cho "
                    "từng phương án bên dưới.</div>", unsafe_allow_html=True)
    mtx = plans.matrix(cfg, counts, db) if counts else {}

    # ---------------------------------------------------------------- 2. PHƯƠNG THỨC
    _step(2, "Phương thức xử lý", "Chọn nơi AI chạy – cùng một quy trình kiểm soát chất lượng cho cả hai")
    hw = _hw()
    key_ok = None if demo else bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    lbase = plans.local_base(cfg)
    lpc = apply_profile(cfg, lbase)
    lmodel = cfg.get_path(f"profiles.{lbase}.llm.local.model") or cfg.get_path("llm.local.model")
    judge = cfg.get_path("llm.local_judge.model") if (cfg.get_path(f"profiles.{lbase}.llm.routes", {}) or {}).get(
        "evaluate") == "local_judge" else None
    models = _server_models(cfg.get_path("llm.local.base_url", "")) if not demo else None
    local_ok = None if demo else (models is not None)
    gpu = ", ".join(f"{g['name']} · {g['vram_gb']:.0f} GB" for g in hw["gpus"]) or "Không phát hiện GPU NVIDIA"
    status = {
        "local": [("GPU máy này", esc(gpu)),
                  ("Model local", esc(lmodel) + (f" + giám khảo {esc(judge)}" if judge else "")),
                  ("Máy chủ AI local", _badge(local_ok, "Đang chạy", "Chưa khởi động")),
                  ("Claude API (hỗ trợ)", _badge(key_ok, "Đã cấu hình", "Chưa có key"))],
        "api": [("Model", esc(plans.friendly(cfg.get_path(f"profiles.{plans.base_profile(cfg, 'api', 'publish')}.llm.model")
                                             or cfg.get_path("llm.model")))),
                ("Số luồng song song", f"{cfg.get_path('translation.workers', 6)} (tăng ở bước 4)"),
                ("Claude API key", _badge(key_ok, "Đã cấu hình", "Chưa có key")),
                ("Yêu cầu máy", "Không cần GPU")],
    }
    cols = st.columns(2, gap="medium")
    for col, ek in zip(cols, plans.ENGINES):
        e = plans.ENGINES[ek]
        sel = ss["np_engine"] == ek
        roles = "".join(f"<span>{esc(a)}</span><b>{esc(b)}</b>" for a, b in e["roles"])
        stt = "".join(f"<div><span>{a}</span><b>{b}</b></div>" for a, b in status[ek])
        col.markdown(
            f"<div class='eng {'sel' if sel else ''}'>"
            + ("<div class='flag'><span class='pill good'>✓ Đang chọn</span></div>" if sel else "")
            + f"<div class='hd'><div class='ic'>{e['icon']}</div><div><div class='t'>{esc(e['label'])}</div>"
            f"<div class='tg'>{esc(e['tagline'])}</div></div></div><div class='roles'>{roles}</div>"
            f"<div class='stt'>{stt}</div><div class='pc'><div class='pro'>＋ {esc(e['pros'])}</div>"
            f"<div class='con'>− {esc(e['cons'])}</div></div></div>", unsafe_allow_html=True)
        col.button("✓ Đã chọn" if sel else "Chọn phương thức này", key=f"np_e_{ek}", width="stretch",
                   type="primary" if sel else "secondary", on_click=lambda k=ek: ss.update(np_engine=k))
    engine = ss["np_engine"]

    # ---------------------------------------------------------------- 3. PHẠM VI
    _step(3, "Phạm vi công việc", "Mỗi mức bao gồm toàn bộ mức trước – chọn đúng nhu cầu để tối ưu chi phí & thời gian")
    cols = st.columns(len(plans.SCOPES), gap="small")
    for i, (col, s) in enumerate(zip(cols, plans.SCOPES), 1):
        sel = ss["np_scope"] == s["key"]
        chk = "".join(f"<span class='{'on' if k in s['stages'] else 'off'}'>{'✓' if k in s['stages'] else '–'} "
                      f"{esc(lbl)}</span>" for k, lbl in plans.STAGE_KEYS)
        est = mtx.get((engine, s["key"]))
        cost = _money(est["estimated_cost_usd_low"], est["estimated_cost_usd_high"]) if est else "—"
        tm = _trange(est) if est else "—"
        col.markdown(
            f"<div class='scope {'sel' if sel else ''}'><div class='lvl'><span>Mức {i}</span>"
            f"<span class='pill {'info' if sel else 'neutral'}'>{esc(s['badge'])}</span></div>"
            f"<div class='t'>{esc(s['label'])}</div><div class='d'>{esc(s['desc'])}</div><div class='chk'>{chk}</div>"
            f"<div class='est'><div><span>Chi phí</span><b>{cost}</b></div><div><span>Thời gian</span><b>{tm}</b>"
            f"</div></div><div class='dl'>Bàn giao: {esc(s['deliver'])}</div></div>", unsafe_allow_html=True)
        col.button("✓ Đã chọn" if sel else "Chọn mức này", key=f"np_s_{s['key']}", width="stretch",
                   type="primary" if sel else "secondary", on_click=lambda k=s["key"]: ss.update(np_scope=k))
    scope = ss["np_scope"]

    # bảng so sánh đầy đủ: phạm vi × phương thức
    head = ("<tr><th></th>" + "".join(f"<th class='c'></th>" for _ in plans.STAGE_KEYS)
            + "".join(f"<th class='g' colspan='2'>{esc(plans.ENGINES[k]['label'])}</th>" for k in plans.ENGINES)
            + "</tr><tr><th>Phạm vi</th>" + "".join(f"<th class='c'>{esc(l)}</th>" for _, l in plans.STAGE_KEYS)
            + "<th class='c'>Chi phí API</th><th class='c'>Thời gian</th>" * len(plans.ENGINES) + "</tr>")
    body = []
    for s in plans.SCOPES:
        tds = "".join(f"<td class='c {'on' if k in s['stages'] else 'off'}'>{'✓' if k in s['stages'] else '–'}</td>"
                      for k, _ in plans.STAGE_KEYS)
        for ek in plans.ENGINES:
            est = mtx.get((ek, s["key"]))
            hl = " hl" if (ek == engine and s["key"] == scope) else ""
            tds += (f"<td class='n{hl}'>{_money(est['estimated_cost_usd_low'], est['estimated_cost_usd_high'])}</td>"
                    f"<td class='n{hl}'>{_trange(est)}</td>" if est
                    else "<td class='n'>—</td><td class='n'>—</td>")
        body.append(f"<tr class='{'sel' if s['key'] == scope else ''}'><td><b>{esc(s['label'])}</b></td>{tds}</tr>")
    st.markdown(f"<div class='card' style='margin-top:14px'><h4>Bảng so sánh phương án</h4>"
                f"<table class='mx'>{head}{''.join(body)}</table><div class='muted' style='margin-top:8px'>"
                + ("Dự toán tính từ tài liệu đã quét (đã trừ phần khớp bộ nhớ dịch & câu lặp). Khoảng thấp – cao "
                   "phản ánh độ khó nội dung. Phương thức local: chi phí là phần gọi Claude hỗ trợ; thời gian theo tốc "
                   "độ GPU đã đo (<code>python -m medtrans hw --save</code>)." if counts
                   else "Tải tài liệu lên để xem dự toán.") + "</div></div>", unsafe_allow_html=True)

    # ---------------------------------------------------------------- 4. XÁC NHẬN
    _step(4, "Xác nhận & chạy", "Quy trình sẽ thực hiện, ai đảm nhiệm từng công đoạn và dự toán cuối cùng")
    left, right = st.columns([3, 2], gap="large")
    with left:
        workers = None
        if engine == "api" and scope != "termbase":
            sp = st.segmented_control("Tốc độ xử lý API", list(plans.SPEEDS), default=None, required=False,
                                      format_func=lambda w: plans.SPEEDS[w], key="np_speed",
                                      help="Số yêu cầu API chạy song song. Cần hạn mức API (rate limit) tương ứng.")
            workers = sp or None
        gate = False
        if scope not in ("termbase", "draft"):
            gate = st.toggle("Dừng sau quét thuật ngữ để chuyên gia kiểm tra & khoá termbase",
                             value=bool(cfg.get_path("terminology.require_lock", False)), key="np_gate")
        with st.expander("Tuỳ chỉnh nâng cao – dùng hồ sơ chi tiết thay cho gói chuẩn"):
            adv = st.toggle("Dùng hồ sơ chi tiết", key="np_adv")
            names = _profiles(cfg)
            adv_name = st.selectbox("Hồ sơ", names, format_func=lambda n: _plabel(cfg, n), disabled=not adv,
                                    index=names.index("premium") if "premium" in names else 0)
            if scans:
                rows = []
                for n in names:
                    ps = [p for a in scans for p in a.get("profiles", []) if p["name"] == n]
                    if ps:
                        rows.append({"Hồ sơ": _plabel(cfg, n), "Chi phí API": _money(
                            sum(p["estimated_cost_usd_low"] for p in ps), sum(p["estimated_cost_usd_high"] for p in ps)),
                            "Thời gian": _trange({"estimated_seconds": sum(p["estimated_seconds"] for p in ps)}),
                            "Mô tả": cfg["profiles"][n].get("description", "")})
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        profile = adv_name if adv else plans.plan_name(engine, scope, workers)
        pc = apply_profile(cfg, profile)
        if not adv:
            flow = "".join(f"<div class='r'><div class='i'>{i}</div><div>{esc(a)}</div>{_who(b)}</div>"
                           for i, (a, b) in enumerate(plans.pipeline(pc), 1))
            st.markdown(f"<div class='card'><h4>Quy trình sẽ thực hiện</h4><div class='flow'>{flow}</div>"
                        "<div class='muted' style='margin-top:8px'>Mỗi công đoạn có điểm lưu – có thể tạm dừng, tiếp "
                        "tục, huỷ ở Hàng đợi; can thiệp từng đoạn ở mục Duyệt.</div></div>", unsafe_allow_html=True)
    with right:
        est = None
        if counts:
            from medtrans.translator import estimate_from_counts
            ch = counts["chars"] if pc.get_path("workflow.scope") == "termbase" else counts["weighted_chars"]
            est = estimate_from_counts(counts["pages"], ch, counts["scanned"], counts["images"], pc, db)
        from medtrans.analysis import calibration_for
        cal = calibration_for(db, profile, domain)
        prob = (f"{cal['pass_rate']:.0f}% <small style='opacity:.8'>(KTC95 {cal['ci_low']:.0f}–{cal['ci_high']:.0f}%)"
                "</small>" if cal else "Chưa hiệu chuẩn")
        title = _plabel(cfg, profile)
        deliver = plans.SCOPE[scope]["deliver"] if not adv else "PDF tiếng Việt + báo cáo"
        st.markdown(
            f"<div class='sum'><div class='hd'>{esc(title)}<small>{esc(', '.join(p.name for p in paths) or 'Chưa có tài liệu')}"
            f"</small></div>"
            f"<div class='k'>Chi phí API dự kiến</div><div class='v'>"
            f"{_money(est['estimated_cost_usd_low'], est['estimated_cost_usd_high']) if est else '—'}</div>"
            f"<div class='k'>Thời gian dự kiến</div><div class='v'>"
            f"{_trange(est) if est else '—'}</div>"
            f"<div class='k'>Xác suất đạt chuẩn</div><div class='v sm'>{prob}</div>"
            f"<div class='k'>Bàn giao</div><div class='v sm'>{esc(deliver)}</div>"
            f"<div class='note'>{'Số luồng: ' + str(pc.get_path('translation.workers')) + ' · ' if est else ''}"
            "Xác suất đạt chuẩn đo bằng mục Hiệu chuẩn trên mẫu của bạn (giám khảo tham chiếu cố định). "
            "Chi phí chỉ gồm token API; chạy local không tính điện năng.</div></div>", unsafe_allow_html=True)
        st.write("")
        warn = None
        if engine == "local" and not adv and local_ok is False:
            warn = "Máy chủ AI local chưa chạy – khởi động Ollama/vLLM trước (xem Cấu hình & hệ thống)."
        elif key_ok is False:
            warn = "Chưa có Claude API key – tạo file .env theo .env.example."
        if warn:
            st.warning(warn)
        go = st.button("🚀 Đưa vào hàng đợi", type="primary", width="stretch",
                       disabled=not paths or pr == "invalid")
    with stepper.container():
        _stepper(3 if paths else 0)
    if go:
        mode = plans.mode_for(profile)
        ids = [q.submit(p, domain, profile, pr if isinstance(pr, tuple) else None, mode=mode,
                        require_lock=gate and mode == "translate", source_lang=lang) for p in paths]
        st.success(f"Đã đưa {len(ids)} tài liệu vào hàng đợi: " + ", ".join(f"#{i}" for i in ids))
        time.sleep(0.6)
        if st.session_state.get("_pages", {}).get("queue"):
            st.switch_page(st.session_state["_pages"]["queue"])


# =====================================================================================  HÀNG ĐỢI
def queue_page():
    page_header("Hàng đợi & tiến độ", "Theo dõi trực tiếp · tạm dừng / tiếp tục / huỷ · tải kết quả")
    _queue_live()


@st.fragment(run_every=2)
def _queue_live():
    cfg, q = state.cfg(), state.queue()
    jobs = q.list(60)
    if not jobs:
        st.info("Hàng đợi trống.")
        return
    act = [j for j in jobs if j["status"] in ("running", "paused", "queued")]
    kpis([("Đang chạy", sum(j["status"] == "running" for j in jobs)), ("Đang chờ", sum(j["status"] == "queued"
                                                                                       for j in jobs)),
          ("Tạm dừng", sum(j["status"] == "paused" for j in jobs)),
          ("Chờ khoá termbase", sum(j["status"] == "awaiting_termbase" for j in jobs)),
          ("Hoàn tất", sum(j["status"] == "done" for j in jobs)), ("Lỗi", sum(j["status"] == "failed" for j in jobs))])
    for j in jobs[:40]:
        with st.container(border=True):
            a, b = st.columns([3, 2])
            a.markdown(f"**#{j['id']} · {esc(j['name'])}** &nbsp; {pill(j['status'])}<br>"
                       f"<span class='muted'>Hồ sơ: {esc(_plabel(cfg, j['profile']))} · chuyên ngành {esc(j['domain'])}"
                       f"{' · trang ' + str(j['page_from']) + '-' + str(j['page_to']) if j['page_from'] else ''}"
                       f"{' · chỉ quét thuật ngữ' if j['mode'] == 'scan_terms' else ''}</span>",
                       unsafe_allow_html=True)
            if j["status"] in ("running", "paused", "queued"):
                a.progress(min(1.0, j["progress"] or 0), text=j["message"] or "Đang chờ...")
            if j["status"] == "failed":
                a.error(j["error"][:500])
            with b:
                bc = st.columns(2)
                if j["status"] == "running":
                    bc[0].button("❚❚ Tạm dừng", key=f"p{j['id']}", on_click=q.control, args=(j["id"], "pause"),
                                 width="stretch")
                if j["status"] == "paused":
                    bc[0].button("▶ Tiếp tục", key=f"r{j['id']}", on_click=q.control, args=(j["id"], "resume"),
                                 width="stretch")
                if j["status"] in ("running", "paused", "queued"):
                    bc[1].button("✕ Huỷ", key=f"c{j['id']}", on_click=q.control, args=(j["id"], "cancel"),
                                 width="stretch")
                if j["status"] in ("failed", "cancelled"):
                    bc[0].button("↻ Chạy lại", key=f"t{j['id']}", on_click=q.control, args=(j["id"], "retry"),
                                 width="stretch")
                res = state.result_of(j)
                for k, label, mime in (("output_pdf", "PDF tiếng Việt", "application/pdf"),
                                       ("report", "Báo cáo", "text/html"),
                                       ("certificate", "Phiếu kiểm định", "text/html"),
                                       ("termbase_xlsx", "Termbase (Excel)",
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")):
                    if res.get(k) and Path(res[k]).exists():
                        st.download_button(f"⬇ {label}", Path(res[k]).read_bytes(), file_name=Path(res[k]).name,
                                           mime=mime, key=f"d{k}{j['id']}")
                if j["status"] == "awaiting_termbase":
                    st.caption("→ Kiểm tra & khoá ở mục **Termbase dự án**")
            rel = res.get("release") if j["status"] == "done" else None
            if rel:
                cls = {"release": "good", "hold": "bad", "draft": "warn"}.get(rel["verdict"], "neutral")
                icon = {"release": "✓", "hold": "!", "draft": "✎"}.get(rel["verdict"], "•")
                st.markdown(f"<span class='pill {cls}'>{icon} {esc(rel['label'])}</span> "
                            f"<span class='muted'>· qua cổng {rel['pass_percent']}% · hiển thị trên PDF "
                            f"{rel['rendered_percent']}% · văn dịch máy "
                            f"{rel['style']['style_flags_per_1000_words']}/1.000 từ</span>", unsafe_allow_html=True)
            if j["status"] == "done" and res.get("segments") is not None:
                st.markdown(f"<span class='muted'>{res.get('segments')} đoạn · đạt chuẩn {res.get('certified', 0)} · "
                            f"MQM TB {res.get('avg_score', 0)} · còn lỗi nặng {res.get('needs_review', 0)} · "
                            f"${res.get('usage', {}).get('estimated_cost_usd', 0)} · {res.get('seconds', 0)} s</span>",
                            unsafe_allow_html=True)
    if act:
        st.caption("Tự làm mới mỗi 2 giây.")


# =====================================================================================  PHÂN TÍCH
def analytics():
    cfg, db = state.cfg(), state.db()
    page_header("Phân tích tài liệu", "Thống kê kiểu SDL Trados: số từ, mức khớp bộ nhớ dịch, lặp lại, thuật ngữ")
    up = st.file_uploader("Tải PDF để phân tích", type=["pdf"], key="an_up")
    files = state.uploaded_files()
    if up:
        state.save_upload(up)
        files = state.uploaded_files()
    if not files:
        st.info("Chưa có tài liệu.")
        return
    c1, c2, c3 = st.columns([3, 2, 1])
    f = c1.selectbox("Tài liệu", files, format_func=lambda p: p.name)
    domain = c2.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="an_dom")
    go = c3.button("Phân tích", type="primary", width="stretch")
    key = f"{f}:{domain}"
    if go:
        from medtrans.analysis import analyze
        with st.spinner("Đang phân tích (không gọi API)..."):
            st.session_state.setdefault("an", {})[key] = analyze(f, cfg, db, domain=domain)
    res = st.session_state.get("an", {}).get(key)
    if not res:
        return
    fi, t = res["file"], res["totals"]
    kpis([("Số trang", fmt_int(fi["pages_analyzed"]), f"{fi['size_mb']} MB · {fi['scanned_pages']} trang scan"),
          ("Số từ cần dịch", fmt_int(t["words"]), f"{fmt_int(t['segments'])} đoạn"),
          ("Quy đổi trang A4", f"{t['a4_pages']}", f"{fmt_int(t['chars'])} ký tự"),
          ("Số từ quy đổi", fmt_int(t["weighted_words"]), f"tiết kiệm {t['tm_saving_percent']}%"),
          ("Từ lặp lại", fmt_int(t["repetition_words"]), "chỉ dịch 1 lần"),
          ("Thuật ngữ", fmt_int(res["terms"]["unique"]), f"{fmt_int(res['terms']['occurrences'])} lượt xuất hiện"),
          ("Không cần dịch", fmt_int(t["non_translatable_words"]), "tài liệu tham khảo, công thức"),
          ("Hình ảnh", fmt_int(fi["images"]), f"{fi['math_blocks']} khối công thức")], accent_first=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader("Phân bổ theo mức khớp (số từ)")
        bars([(b["label"], b["words"], f"{fmt_int(b['words'])} từ · {b['percent']}%") for b in res["bands"]])
        df = pd.DataFrame(res["bands"])[["label", "segments", "words", "chars", "percent", "weight"]]
        df.columns = ["Mức khớp", "Đoạn", "Từ", "Ký tự", "% từ", "Hệ số công việc"]
        st.dataframe(df, hide_index=True, width="stretch")
    with c2:
        st.subheader("Dự báo theo hồ sơ")
        for p in res.get("profiles", []):
            cal = p.get("calibration")
            st.markdown(f"<div class='card'><h4>{esc(p['label'])}</h4><div class='muted'>"
                        f"{_money(p['estimated_cost_usd_low'], p['estimated_cost_usd_high'])} · "
                        f"{esc(p['estimated_time_low'])}–{esc(p['estimated_time_high'])}"
                        + (f" · đạt chuẩn {cal['pass_rate']:.0f}% (KTC95 {cal['ci_low']:.0f}–{cal['ci_high']:.0f}%)"
                           if cal else " · chưa hiệu chuẩn") + "</div></div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Thuật ngữ xuất hiện nhiều")
        if res["terms"]["top"]:
            st.dataframe(pd.DataFrame(res["terms"]["top"]).rename(columns={
                "en": "Thuật ngữ", "vi": "Tiếng Việt", "freq": "Tần suất", "origin": "Nguồn"}),
                hide_index=True, width="stretch", height=320)
    with c2:
        st.subheader("Câu lặp nhiều nhất")
        if res["top_repetitions"]:
            st.dataframe(pd.DataFrame(res["top_repetitions"]).rename(columns={"text": "Nội dung", "count": "Số lần"}),
                         hide_index=True, width="stretch", height=320)
        else:
            st.caption("Không có câu lặp.")
    from medtrans.analysis import export_xlsx
    out = Path(tempfile.mkdtemp()) / f"{Path(f).stem}_analysis.xlsx"
    export_xlsx(res, out)
    st.download_button("⬇ Xuất báo cáo phân tích (Excel)", out.read_bytes(), file_name=out.name)


# =====================================================================================  TERMBASE DỰ ÁN
def termbase_page():
    cfg, db, q = state.cfg(), state.db(), state.queue()
    page_header("Termbase dự án", "Quét → kiểm tra (nội bộ/chuyên gia ngoài) → khoá → dịch chính thức thống nhất")
    jobs = db.query("SELECT j.job_id, j.pdf_path, j.domain, j.status, COUNT(t.en) n, SUM(t.status='locked') l "
                    "FROM jobs j JOIN job_terms t ON t.job_id=j.job_id GROUP BY j.job_id ORDER BY j.updated_at DESC")
    if not jobs:
        st.info("Chưa có termbase. Ở **Dự án mới** chọn *Chỉ quét thuật ngữ* hoặc bật chốt chặn termbase.")
        return
    lab = {f"{Path(j['pdf_path']).name} [{j['domain']}] – {j['n']} thuật ngữ"
           + (" · ĐÃ KHOÁ" if j["l"] else ""): j for j in jobs}
    j = lab[st.selectbox("Dự án", list(lab))]
    rows = db.job_terms(j["job_id"])
    locked = any(r["status"] == "locked" for r in rows)
    kpis([("Thuật ngữ", fmt_int(len(rows))), ("Đã khoá", fmt_int(sum(r["status"] == "locked" for r in rows))),
          ("Bị loại", fmt_int(sum(r["status"] == "rejected" for r in rows))),
          ("Có nhiều phương án", fmt_int(sum(bool(r["variants"]) for r in rows))),
          ("Tra cứu web", fmt_int(sum(r["origin"] == "web" for r in rows)))])
    t1, t2 = st.tabs(["✏️ Kiểm tra trực tiếp", "⇅ Trao đổi file với chuyên gia"])
    with t1:
        df = pd.DataFrame([{"Thuật ngữ gốc": r["en"], "Tiếng Việt chốt": r["vi"],
                            "Trạng thái": "Loại" if r["status"] == "rejected" else "Duyệt", "Tần suất": r["freq"],
                            "Nguồn": ORIGIN.get(r["origin"], r["origin"]), "Tin cậy": round(r["confidence"] or 0, 2),
                            "Phương án khác": r["variants"], "Ngữ cảnh": r["context"]} for r in rows])
        ed = st.data_editor(df, hide_index=True, width="stretch", height=460, num_rows="dynamic",
                            disabled=["Tần suất", "Nguồn", "Tin cậy", "Phương án khác", "Ngữ cảnh"],
                            column_config={"Trạng thái": st.column_config.SelectboxColumn(options=["Duyệt", "Loại"])})
        if st.button("🔒 Khoá termbase", type="primary"):
            from medtrans.termbase import lock
            recs = [{"en": r["Thuật ngữ gốc"], "vi_final": r["Tiếng Việt chốt"], "status": r["Trạng thái"],
                     "freq": r["Tần suất"] or 0, "context": r["Ngữ cảnh"] or ""} for _, r in ed.iterrows()
                    if isinstance(r["Thuật ngữ gốc"], str) and r["Thuật ngữ gốc"].strip()]
            st.session_state["tb_lock"] = lock(db, j["job_id"], recs, j["domain"])
            st.rerun()
    with t2:
        from medtrans.termbase import export_tbx, export_xlsx, lock, read_xlsx
        tmp = Path(tempfile.mkdtemp())
        x = export_xlsx(rows, tmp / f"{Path(j['pdf_path']).stem}_termbase.xlsx", Path(j["pdf_path"]).name)
        tb = export_tbx(rows, tmp / f"{Path(j['pdf_path']).stem}_termbase.tbx")
        c1, c2 = st.columns(2)
        c1.download_button("⬇ Tải termbase (Excel) để kiểm tra", x.read_bytes(), file_name=x.name)
        c2.download_button("⬇ Tải TBX (Trados MultiTerm / memoQ)", tb.read_bytes(), file_name=tb.name)
        upf = st.file_uploader("Tải lên termbase đã kiểm tra (Excel)", type=["xlsx"], key="tb_up")
        if upf and st.button("🔒 Nhập & khoá"):
            p = tmp / upf.name
            p.write_bytes(upf.getbuffer())
            st.session_state["tb_lock"] = lock(db, j["job_id"], read_xlsx(p), j["domain"])
            st.rerun()
    if st.session_state.get("tb_lock"):
        r = st.session_state.pop("tb_lock")
        st.success(f"Đã khoá {r['locked']} thuật ngữ, loại {r['rejected']}. Thuật ngữ khoá được áp dụng bắt buộc "
                   "và thống nhất trong toàn bộ bản dịch.")
    if locked:
        waiting = [x for x in q.list(200) if x["job_id"] == j["job_id"] and x["status"] == "awaiting_termbase"]
        prof = st.selectbox("Hồ sơ dịch chính thức", _profiles(cfg), format_func=lambda n: _plabel(cfg, n),
                            index=_profiles(cfg).index(cfg.get("default_profile", "premium")))
        if st.button("🚀 Dịch chính thức với termbase đã khoá", type="primary"):
            src = waiting[0] if waiting else None
            pr = (src["page_from"], src["page_to"]) if src and src["page_from"] else None
            qid = q.submit(j["pdf_path"], j["domain"], prof, pr)
            st.success(f"Đã đưa vào hàng đợi #{qid}")


# =====================================================================================  DUYỆT & CAN THIỆP
def review_page():
    cfg, db = state.cfg(), state.db()
    page_header("Duyệt & can thiệp", "Tuỳ chọn: xem lỗi còn lại, sửa tay, dựng lại PDF không tốn token")
    jobs = db.query("SELECT job_id, pdf_path, domain, status FROM jobs ORDER BY updated_at DESC")
    if not jobs:
        st.info("Chưa có tài liệu.")
        return
    lab = {f"{Path(j['pdf_path']).name} [{j['domain']}]": j for j in jobs}
    j = lab[st.selectbox("Tài liệu", list(lab))]
    segs = sorted(db.segments(j["job_id"]).values(), key=lambda s: (s["page"], s["seg_id"]))
    cnt = {k: sum(s["status"] == k for s in segs) for k in ("certified", "done", "needs_review", "tm", "draft",
                                                            "failed")}
    kpis([("Đoạn", fmt_int(len(segs))), ("Đạt chuẩn", fmt_int(cnt["certified"])), ("Đạt", fmt_int(cnt["done"])),
          ("Còn lỗi nặng", fmt_int(cnt["needs_review"])), ("Bộ nhớ dịch", fmt_int(cnt["tm"])),
          ("Bản thô", fmt_int(cnt["draft"]))])
    flt = st.segmented_control("Lọc", ["Chưa đạt chuẩn", "Còn lỗi nặng", "Tất cả"], default="Chưa đạt chuẩn")
    if flt == "Chưa đạt chuẩn":
        segs = [s for s in segs if s["status"] not in ("certified", "tm")]
    elif flt == "Còn lỗi nặng":
        segs = [s for s in segs if s["status"] in ("needs_review", "failed")]
    st.caption(f"{len(segs)} đoạn. Giữ nguyên mã ⟦n⟧ và ⟦¶⟧ khi sửa.")
    for s in segs[:150]:
        with st.expander(f"Trang {s['page'] + 1} · {s['role']} · điểm {s['score']} · {s['seg_id']}"):
            st.markdown(pill(s["status"]), unsafe_allow_html=True)
            st.markdown("**Bản gốc**")
            st.write(s["src"])
            for i in s["issues"]:
                if i.get("severity") == "error":
                    st.error(i.get("message", ""))
                elif i.get("severity") == "warning":
                    st.warning(i.get("message", ""))
            new = st.text_area("Bản dịch", s["tgt"], key=f"t_{j['job_id']}_{s['seg_id']}", height=140)
            if st.button("💾 Lưu (đánh dấu đã duyệt tay)", key=f"b_{j['job_id']}_{s['seg_id']}"):
                db.segment_save(j["job_id"], s["seg_id"], page=s["page"], kind=s["kind"], role=s["role"],
                                src=s["src"], tgt=new, status="certified", score=100,
                                issues=[{"severity": "info", "code": "human", "message": "Đã duyệt tay"}])
                db.tm_add(s["src"], new, j["domain"], doc_name=j["job_id"], role=s["role"], quality=100,
                          approved=True, origin="human")
                st.toast("Đã lưu vào bộ nhớ dịch (đã duyệt).")
    if st.button("🔁 Dựng lại PDF & phiếu kiểm định từ dữ liệu hiện tại", type="primary"):
        last = db.query("SELECT profile FROM queue WHERE pdf_path=? AND domain=? AND mode='translate' "
                        "ORDER BY id DESC LIMIT 1", (j["pdf_path"], j["domain"]))
        qid = state.queue().submit(j["pdf_path"], j["domain"],
                                   last[0]["profile"] if last else cfg.get("default_profile", "premium"))
        st.success(f"Đã đưa vào hàng đợi #{qid} – các đoạn đã có sẽ được dùng lại, không dịch lại.")
    _lqa_panel(cfg, db, j)


def _lqa_panel(cfg, db, j) -> None:
    """Kiểm định mẫu bởi chuyên gia & thử nghiệm mù người – máy."""
    from medtrans import lqa
    st.subheader("Kiểm định độc lập bởi chuyên gia")
    st.markdown("<div class='muted'>Chuyên gia chỉ đọc một <b>mẫu ngẫu nhiên</b> thay vì cả cuốn. Không phát hiện lỗi "
                "nặng trong mẫu ⇒ với độ tin cậy đã chọn, tỉ lệ đoạn lỗi nặng của <b>toàn bộ</b> bản dịch không vượt "
                "ngưỡng. Bản sửa của chuyên gia được áp vào bản dịch và bộ nhớ dịch.</div>", unsafe_allow_html=True)
    out_dir = cfg.resolve("workspace/lqa")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(j["pdf_path"]).stem
    t1, t2 = st.tabs(["Kiểm định mẫu", "Thử nghiệm mù người – máy"])
    with t1:
        c1, c2, c3 = st.columns(3)
        conf = c1.select_slider("Độ tin cậy", [0.90, 0.95, 0.99], value=0.95, format_func=lambda x: f"{x:.0%}",
                                key="lqa_conf")
        rate = c2.select_slider("Ngưỡng lỗi nặng tối đa", [0.01, 0.02, 0.03, 0.05], value=0.03,
                                format_func=lambda x: f"{x:.0%}", key="lqa_rate")
        n = lqa.sample_size(conf, rate)
        c3.metric("Số đoạn chuyên gia cần đọc", fmt_int(n))
        if st.button("📤 Xuất mẫu kiểm định (Excel)", key="lqa_exp"):
            r = lqa.export_sample(db, j["job_id"], out_dir / f"{stem}_kiem_dinh_mau.xlsx", n, conf, rate)
            st.session_state["lqa_file"] = r["file"]
        f = st.session_state.get("lqa_file")
        if f and Path(f).exists():
            st.download_button("⬇ Tải file mẫu gửi chuyên gia", Path(f).read_bytes(), file_name=Path(f).name,
                               key="lqa_dl")
        up = st.file_uploader("Nhập file chuyên gia đã chấm", type=["xlsx"], key="lqa_up")
        if up and st.button("📥 Nhập kết quả", key="lqa_imp"):
            tmp = out_dir / f"_in_{up.name}"
            tmp.write_bytes(up.getbuffer())
            r = lqa.import_sample(db, j["job_id"], tmp, max_rate=rate, domain=j["domain"])
            kpis([("Đoạn đã chấm", fmt_int(r["n"])), ("Lỗi nặng", fmt_int(r["defects"])),
                  ("Lỗi nhỏ", fmt_int(r["minor"])), ("Trần tỉ lệ lỗi (95%)", f"{r['upper_percent']}%"),
                  ("Kết luận", "ĐẠT" if r["passed"] else "CHƯA ĐẠT"), ("Bản sửa đã áp", fmt_int(r["fixed"]))])
            st.caption("Dựng lại PDF để phiếu kiểm định cập nhật kết quả kiểm định mẫu.")
        last = lqa.latest(db, j["job_id"])
        if last:
            st.markdown(f"Lần kiểm định gần nhất: {pill('certified' if last['passed'] else 'needs_review')} "
                        f"<span class='muted'>{last['defects']} lỗi nặng / {last['n']} đoạn · trần "
                        f"{last['upper_percent']}%</span>", unsafe_allow_html=True)
    with t2:
        st.markdown("<div class='muted'>Dùng các đoạn đã có <b>bản dịch người</b> (nhập TMX sách đã xuất bản). Hệ thống "
                    "trộn bản người và bản máy, ẩn nguồn gốc; chuyên gia chấm như nhau; sau đó mở khoá để so sánh."
                    "</div>", unsafe_allow_html=True)
        if st.button("📤 Xuất bộ thử nghiệm mù", key="blind_exp"):
            r = lqa.export_blind(db, j["job_id"], out_dir / f"{stem}_thu_nghiem_mu.xlsx")
            if not r["pairs"]:
                st.warning("Chưa có đoạn nào có bản dịch người trong bộ nhớ dịch – nhập TMX trước.")
            st.session_state["blind"] = r
        r = st.session_state.get("blind")
        if r and r.get("pairs"):
            st.download_button("⬇ File gửi chuyên gia", Path(r["file"]).read_bytes(), file_name=Path(r["file"]).name,
                               key="blind_dl")
            st.caption(f"Khoá giải mã lưu riêng tại {r['key']} – không gửi cho người chấm.")
        upb = st.file_uploader("Nhập file thử nghiệm mù đã chấm", type=["xlsx"], key="blind_up")
        if upb and r and st.button("🔓 Mở khoá & so sánh", key="blind_imp"):
            tmp = out_dir / f"_in_{upb.name}"
            tmp.write_bytes(upb.getbuffer())
            res = lqa.import_blind(db, tmp, r["key"])
            pd_rows = [{"Nguồn": "Người", **{k: res["human"][k] for k in ("n", "ok_percent", "severe_percent", "score")}},
                       {"Nguồn": "Máy (MedTrans)", **{k: res["ai"][k] for k in ("n", "ok_percent", "severe_percent",
                                                                               "score")}}]
            st.dataframe(pd.DataFrame(pd_rows).rename(columns={"n": "Đoạn", "ok_percent": "% đạt",
                                                               "severe_percent": "% lỗi nặng", "score": "Điểm"}),
                         hide_index=True)
            st.success(res["verdict"])


# =====================================================================================  HIỆU CHUẨN
def calibration_page():
    cfg, db = state.cfg(), state.db()
    page_header("Hiệu chuẩn chất lượng / chi phí",
                "Chạy thử các hồ sơ trên trang mẫu của bạn · một giám khảo tham chiếu chấm tất cả · có khoảng tin cậy")
    files = state.uploaded_files()
    up = st.file_uploader("PDF mẫu", type=["pdf"], key="cal_up")
    if up:
        state.save_upload(up)
        files = state.uploaded_files()
    if files:
        c1, c2, c3 = st.columns([3, 1, 2])
        f = c1.selectbox("Tài liệu mẫu", files, format_func=lambda p: p.name)
        pr = c2.text_input("Trang mẫu", "1-10")
        domain = c3.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="cal_dom")
        profs = st.multiselect("Hồ sơ cần so sánh", _profiles(cfg),
                               default=[p for p in ("economy", "balanced", "premium") if p in _profiles(cfg)],
                               format_func=lambda n: _plabel(cfg, n))
        ref = st.selectbox("Giám khảo tham chiếu (chấm tất cả hồ sơ cùng một thước đo)",
                           [p for p in ("premium", "local_quality") if p in _profiles(cfg)],
                           format_func=lambda n: _plabel(cfg, n),
                           help="Chọn 'Local – chất lượng cao' để hiệu chuẩn hoàn toàn offline")
        st.caption("Gợi ý: 10–20 trang đại diện (chữ, bảng, hình). Chi phí hiệu chuẩn ≈ tổng chi phí các hồ sơ trên "
                   "số trang mẫu + 1 lượt giám khảo tham chiếu mỗi hồ sơ.")
        if st.button("▶ Chạy hiệu chuẩn", type="primary", disabled=not profs):
            from medtrans.calibrate import calibrate
            a, _, b = pr.partition("-")
            bar = st.progress(0.0)
            with st.spinner("Đang hiệu chuẩn..."):
                res = calibrate(f, cfg, db, profs, page_range=(int(a), int(b or a)), domain=domain,
                                progress=lambda x, m: bar.progress(min(1.0, x), m), ref_profile=ref)
            st.success("Hoàn tất hiệu chuẩn.")
    rows = db.query("SELECT * FROM calibration ORDER BY created_at DESC LIMIT 50")
    if rows:
        st.subheader("Kết quả hiệu chuẩn")
        df = pd.DataFrame([{"Hồ sơ": _plabel(cfg, r["profile"]), "Model": r["model"], "Chuyên ngành": r["domain"],
                            "Đoạn": r["segments"], "MQM TB": r["avg_mqm"], "Đạt chuẩn %": r["pass_rate"],
                            "KTC95 %": f"{r['ci_low']:.0f}–{r['ci_high']:.0f}", "Còn lỗi critical %": r["critical_rate"],
                            "USD / trang A4": r["cost_per_a4"], "Giây / trang A4": r["sec_per_a4"],
                            "Mẫu": r["sample"], "Lúc": time.strftime("%d/%m %H:%M", time.localtime(r["created_at"]))}
                           for r in rows])
        st.dataframe(df, hide_index=True, width="stretch")
        latest = {}
        for r in rows:
            latest.setdefault(r["profile"], r)
        st.subheader("So sánh tỉ lệ đạt chuẩn (lần hiệu chuẩn gần nhất)")
        bars([(_plabel(cfg, k), v["pass_rate"], f"{v['pass_rate']:.0f}% · ${v['cost_per_a4']:.2f}/A4")
              for k, v in latest.items()], unit="%")


# =====================================================================================  KHO THUẬT NGỮ
def glossary_page():
    cfg, db = state.cfg(), state.db()
    page_header("Kho thuật ngữ", "Thuật ngữ chuẩn dùng chung mọi dự án · tự làm giàu theo bằng chứng đạt chuẩn")
    from medtrans.glossary import export_csv, import_file
    appr = db.terms(status="approved", src_lang=None)
    cand = db.terms(status="candidate", src_lang=None)
    kpis([("Đã duyệt", fmt_int(len(appr))), ("Đang tích luỹ bằng chứng", fmt_int(len(cand))),
          ("Từ termbase dự án", fmt_int(sum(t["source"] == "termbase" for t in appr))),
          ("Tự duyệt", fmt_int(sum("tự duyệt" in (t["note"] or "") or "kiểm định" in (t["note"] or "") for t in appr)))])
    t1, t2, t3 = st.tabs(["Đã duyệt", "Đang tích luỹ", "Nhập / thêm"])
    with t1:
        qtxt = st.text_input("Tìm", key="g_q")
        rows = [t for t in appr if qtxt.lower() in (t["en"] + " " + t["vi"]).lower()] if qtxt else appr
        if rows:
            st.dataframe(pd.DataFrame(rows)[["en", "vi", "domain", "category", "evidence", "source", "note"]].rename(
                columns={"en": "Thuật ngữ", "vi": "Tiếng Việt", "domain": "Chuyên ngành", "category": "Loại",
                         "evidence": "Bằng chứng", "source": "Nguồn", "note": "Ghi chú"}),
                hide_index=True, width="stretch", height=480)
        out = Path(tempfile.mkdtemp()) / "glossary_export.csv"
        export_csv(db, out)
        st.download_button("⬇ Xuất CSV", out.read_bytes(), file_name="glossary_export.csv")
    with t2:
        st.caption(f"Tự duyệt khi dùng nhất quán trong ≥ {cfg.get_path('quality.term_min_evidence', 3)} đoạn đạt chuẩn "
                   "và qua kiểm định độc lập. Có thể duyệt/loại tay.")
        if cand:
            df = pd.DataFrame(cand)[["id", "en", "vi", "domain", "evidence", "source", "note"]]
            df.insert(0, "Duyệt", False)
            df.insert(1, "Loại", False)
            ed = st.data_editor(df, hide_index=True, width="stretch", column_config={"id": None}, key="cand_ed")
            if st.button("Áp dụng"):
                for _, r in ed.iterrows():
                    if r["Duyệt"]:
                        db.set_term_status(int(r["id"]), "approved")
                    elif r["Loại"]:
                        db.set_term_status(int(r["id"]), "rejected")
                st.rerun()
    with t3:
        gf = st.file_uploader("CSV / Excel / TBX", type=["csv", "xlsx", "tbx", "txt"], key="gl_up")
        gdom = st.text_input("Chuyên ngành mặc định", cfg.get_path("translation.domain"), key="gl_dom")
        if gf and st.button("Nhập"):
            p = Path(tempfile.mkdtemp()) / gf.name
            p.write_bytes(gf.getbuffer())
            st.success(f"Đã nhập {import_file(db, p, default_domain=gdom)} thuật ngữ.")
        with st.form("add_term"):
            a1, a2, a3 = st.columns(3)
            en = a1.text_input("Thuật ngữ gốc")
            vi = a2.text_input("Tiếng Việt")
            dom = a3.text_input("Chuyên ngành", cfg.get_path("translation.domain"))
            note = st.text_input("Ghi chú ngữ cảnh")
            keep = st.checkbox("Giữ nguyên (không dịch)")
            if st.form_submit_button("Thêm") and en:
                db.upsert_term(en, vi, dom, note=note, keep_original=keep)
                st.success("Đã thêm.")


# =====================================================================================  BỘ NHỚ DỊCH
def tm_page():
    cfg, db = state.cfg(), state.db()
    page_header("Bộ nhớ dịch", "Chỉ đoạn đạt chuẩn được dùng lại · trao đổi TMX với Trados / memoQ / OmegaT")
    from medtrans import tm as tm_mod
    s = db.tm_stats()
    kpis([("Cặp câu", fmt_int(s["segments"])), ("Đạt chuẩn / đã duyệt", fmt_int(s["approved"])),
          ("Điểm TB", s["avg_quality"])])
    tf = st.file_uploader("Nhập TMX / bảng song ngữ (CSV, Excel)", type=["tmx", "csv", "xlsx"], key="tm_up")
    tdom = st.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="tm_dom")
    if tf and st.button("Nhập"):
        p = Path(tempfile.mkdtemp()) / tf.name
        p.write_bytes(tf.getbuffer())
        n = tm_mod.import_tmx(db, p, tdom) if p.suffix.lower() == ".tmx" else tm_mod.import_bilingual_table(db, p, tdom)
        st.success(f"Đã nhập {n} cặp câu.")
    out = Path(tempfile.mkdtemp()) / "medtrans_memory.tmx"
    n = tm_mod.export_tmx(db, out, min_quality=int(cfg.get_path("memory.tm_min_quality", 97)))
    st.download_button(f"⬇ Xuất TMX ({fmt_int(n)} cặp câu đạt chuẩn)", out.read_bytes(), file_name=out.name)


# =====================================================================================  CẤU HÌNH
@st.cache_data(ttl=120, show_spinner=False)
def _doctor(_k: int = 0) -> list[dict]:
    from medtrans.doctor import run
    return run(load_config(), call_api=True)


def _setup_panel(cfg, key_ok: bool) -> None:
    """Thiết lập lần đầu & kiểm tra hệ thống."""
    from medtrans.doctor import check_api_key, ready, save_api_key
    st.subheader("Thiết lập & kiểm tra hệ thống")
    with st.container(border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        key = c1.text_input("Claude API key", type="password", placeholder="sk-ant-…",
                            help="Lấy tại console.anthropic.com → API Keys. Khoá được lưu trong file .env trên máy này.")
        if c2.button("💾 Lưu & kiểm tra", width="stretch", disabled=not key.strip()):
            save_api_key(key)
            r = check_api_key(load_config())
            (st.success if r["status"] == "ok" else st.error)(f"{r['detail']}" + (f" – {r['fix']}" if r["fix"] else ""))
            _doctor.clear()
        if st.button("↻ Kiểm tra lại toàn bộ"):
            _doctor.clear()
        items = _doctor()
        icon = {"ok": ("✓", "good"), "warn": ("!", "warn"), "fail": ("✕", "bad")}
        rows = "".join(
            f"<tr><td><span class='pill {icon[i['status']][1]}'>{icon[i['status']][0]}</span></td>"
            f"<td><b>{esc(i['name'])}</b></td><td>{esc(i['detail'])}"
            + (f"<div class='muted'>→ {esc(i['fix'])}</div>" if i["status"] != "ok" and i["fix"] else "")
            + "</td></tr>" for i in items)
        st.markdown(f"<table class='tbl'>{rows}</table>", unsafe_allow_html=True)
        if ready(items):
            st.success("Hệ thống sẵn sàng chạy.")
        else:
            st.error("Chưa sẵn sàng – xử lý các mục ✕ ở trên.")


def settings_page():
    cfg, db = state.cfg(), state.db()
    page_header("Cấu hình & hệ thống", "Kết nối API, tài nguyên máy, quy ước chuyên ngành, cấu hình")
    from medtrans.scan import tesseract_available
    _setup_panel(cfg, True)
    key_ok = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    kpis([("Claude API key", "Đã cấu hình" if key_ok else "Chưa có", ".env"),
          ("Tesseract OCR", "Sẵn sàng" if tesseract_available() else "Chưa cài", "PDF scan & chữ trong hình"),
          ("Nhân CPU", os.cpu_count() or "?", "OCR & dàn trang song song"),
          ("Hồ sơ mặc định", _plabel(cfg, cfg.get("default_profile", "premium")))])
    st.subheader("Phần cứng máy này & đề xuất")
    from medtrans.hardware import detect, recommend
    hw = detect()
    rec = recommend(hw)
    gpu = ", ".join(f"{g['name']} ({g['vram_gb']} GB)" for g in hw["gpus"]) or "không phát hiện GPU NVIDIA"
    st.markdown(f"<div class='card'><b>{esc(rec['tier'])}</b><div class='muted'>GPU: {esc(gpu)} · RAM: "
                f"{hw['ram_gb']} GB</div><div style='margin-top:6px'>Model local đề xuất: <b>{esc(rec['local_model'])}"
                f"</b> · Hồ sơ đề xuất: <b>{esc(rec['profile'])}</b></div><div class='muted'>{esc(rec['note'])}</div>"
                + (f"<div class='muted'>Nâng cấp kế tiếp: {esc(rec['upgrade'])}</div>" if rec.get("upgrade") else "") +
                "<div class='muted'>Đo tốc độ thật: <code>python -m medtrans hw --save</code></div></div>",
                unsafe_allow_html=True)
    st.subheader("Model chạy local")
    import httpx2
    for name, label in (("local", "Máy chủ model local (Ollama / vLLM / llama.cpp / LM Studio)"),
                        ("local_judge", "Giám khảo local thứ hai (hồ sơ Local Pro)"),
                        ("medcrab", "MedCrab-1.5B (dịch nháp)")):
        c = cfg.get_path(f"llm.{name}", {}) or {}
        url = (c.get("base_url") or "").rstrip("/")
        try:
            r = httpx2.get(f"{url}/models", timeout=2, trust_env=False)
            ms = ", ".join(m.get("id", "") for m in r.json().get("data", [])) or "—"
            st.markdown(f"{pill('done')} **{label}** · `{url}` · model: {esc(ms)}", unsafe_allow_html=True)
        except Exception:  # noqa: BLE001
            st.markdown(f"{pill('cancelled')} **{label}** · `{url}` – chưa chạy (xem docs/CHAY_LOCAL.md)",
                        unsafe_allow_html=True)
    st.subheader("Nhà cung cấp AI & dự phòng")
    prov = cfg.get_path("llm.providers", {}) or {}
    chain = cfg.get_path("llm.failover", []) or []
    st.markdown(f"<div class='muted'>Chính: <b>{esc(cfg.get_path('llm.provider'))}</b> · Dự phòng: "
                f"<b>{esc(' → '.join(chain) if chain else 'tắt (chạy 1 mô thức chuẩn)')}</b>. Mọi kết quả, dù từ nhà cung "
                "cấp nào, đều qua cùng cổng kiểm tra máy + giám khảo + kiểm toán trung thành.</div>",
                unsafe_allow_html=True)
    if prov:
        st.dataframe(pd.DataFrame([{"Nhà cung cấp": n, "Model": c.get("model") or "— (chưa điền)",
                                    "Khoá API": "Đã có" if os.environ.get(c.get("api_key_env") or "") else "Chưa có",
                                    "Giá USD/1M token": " / ".join(map(str, c.get("price_per_mtok") or [])) or "—"}
                                   for n, c in prov.items()]), hide_index=True, width="stretch")
    st.caption("Bật dự phòng: llm.failover trong config.yaml · Kiểm tra: python -m medtrans providers")
    st.subheader("Quy ước văn phong theo chuyên ngành")
    dn = st.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="dn_dom")
    notes = st.text_area("Quy ước", db.domain_notes(dn), height=160)
    if st.button("Lưu quy ước"):
        db.set_domain_notes(dn, notes)
        st.success("Đã lưu.")
    with st.expander("config.yaml"):
        st.code((ROOT / "config.yaml").read_text(encoding="utf-8"), language="yaml")
    with st.expander("Nguyên tắc giữ nguyên (data/preserve_rules.yaml)"):
        st.code((ROOT / "data" / "preserve_rules.yaml").read_text(encoding="utf-8"), language="yaml")
