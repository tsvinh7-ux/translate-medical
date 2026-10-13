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
    return f"${lo:,.0f}–{hi:,.0f}" if hi >= 20 else f"${lo:.2f}–{hi:.2f}"


def _plabel(cfg, name: str) -> str:
    return (cfg.get("profiles") or {}).get(name, {}).get("label", name)


# =====================================================================================  TỔNG QUAN
def dashboard():
    cfg, db, q = state.cfg(), state.db(), state.queue()
    page_header("Tổng quan", "Tình hình vận hành, chất lượng và dữ liệu tích luỹ")
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
def new_project():
    cfg, db, q = state.cfg(), state.db(), state.queue()
    page_header("Dự án mới", "Tải tài liệu, chọn hồ sơ chất lượng/chi phí và đưa vào hàng đợi")
    files = st.file_uploader("Tài liệu PDF (có thể chọn nhiều file)", type=["pdf"], accept_multiple_files=True)
    c1, c2, c3 = st.columns(3)
    lang = c1.selectbox("Ngôn ngữ nguồn → tiếng Việt", list(LANGS),
                        format_func=lambda c: f"{LANGS[c].name_vi.capitalize()} ({c})")
    domain = c2.text_input("Chuyên ngành", cfg.get_path("translation.domain", "general_medicine"),
                           help="cardiology, oncology, pharmacology... Kho thuật ngữ & bộ nhớ dịch lưu theo chuyên ngành")
    pages = c3.text_input("Phạm vi trang (để trống = toàn bộ)", placeholder="ví dụ 1-50")
    mode = st.radio("Chế độ", ["Dịch (có thể dừng chờ kiểm tra termbase)", "Chỉ quét thuật ngữ → termbase"],
                    horizontal=True)
    gate = st.checkbox("Dừng sau khi quét thuật ngữ để kiểm tra & khoá termbase trước khi dịch chính thức",
                       value=bool(cfg.get_path("terminology.require_lock", False)),
                       disabled=mode.startswith("Chỉ"))

    st.subheader("Hồ sơ chất lượng / chi phí")
    paths = [state.save_upload(f) for f in files] if files else []
    forecast = {}
    if paths and st.button("📊 Phân tích & dự báo cho các file đã chọn"):
        from medtrans.analysis import analyze
        with st.spinner("Đang phân tích (không gọi API)..."):
            for pth in paths:
                st.session_state.setdefault("analysis", {})[str(pth)] = analyze(pth, cfg, db, domain=domain)
    for pth in paths:
        a = st.session_state.get("analysis", {}).get(str(pth))
        if a:
            for pr in a.get("profiles", []):
                f = forecast.setdefault(pr["name"], {"c_lo": 0, "c_hi": 0, "sec": 0, "cal": pr.get("calibration")})
                f["c_lo"] += pr["estimated_cost_usd_low"]
                f["c_hi"] += pr["estimated_cost_usd_high"]
                f["sec"] += pr["estimated_seconds"]
    names = _profiles(cfg)
    default = names.index(cfg.get("default_profile", "premium")) if cfg.get("default_profile") in names else 0
    choice = st.radio("Chọn hồ sơ", names, index=default, horizontal=True, format_func=lambda n: _plabel(cfg, n),
                      label_visibility="collapsed")
    cols = []
    for i in range(0, len(names), 4):
        cols.extend(st.columns(4))
    for col, name in zip(cols, names):
        prof = cfg["profiles"][name]
        pc = apply_profile(cfg, name)
        f = forecast.get(name)
        cal = (f or {}).get("cal")
        if cal is None:
            from medtrans.analysis import calibration_for
            cal = calibration_for(db, name, domain)
        q_txt = (f"{cal['pass_rate']:.0f}% <span class='muted'>(KTC95 {cal['ci_low']:.0f}–{cal['ci_high']:.0f}%)</span>"
                 if cal else "<span class='muted'>chưa hiệu chuẩn</span>")
        from medtrans.translator import _fmt_dur
        rows = [("Model", esc(pc.get_path("llm.model")) + f" · {esc(pc.get_path('llm.effort'))}"),
                ("Chi phí dự báo", _money(f["c_lo"], f["c_hi"]) if f else "—"),
                ("Thời gian dự báo", f"{_fmt_dur(f['sec'] * .7)}–{_fmt_dur(f['sec'] * 1.6)}" if f else "—"),
                ("Xác suất đạt chuẩn", q_txt), ("MQM hiệu chuẩn", f"{cal['avg_mqm']:.1f}" if cal else "—")]
        col.markdown(f"<div class='prof {'sel' if name == choice else ''}'><div class='t'>{esc(prof.get('label'))}</div>"
                     f"<div class='d'>{esc(prof.get('description', ''))}</div>"
                     + "".join(f"<div class='row'><span>{k}</span><b>{v}</b></div>" for k, v in rows)
                     + "</div>", unsafe_allow_html=True)
    st.caption("Xác suất đạt chuẩn = tỉ lệ đoạn đạt MQM ≥ ngưỡng chứng nhận khi hiệu chuẩn trên mẫu của bạn "
               "(giám khảo tham chiếu cố định), kèm khoảng tin cậy 95%. Chạy ở mục **Hiệu chuẩn**.")
    st.divider()
    if st.button("🚀 Đưa vào hàng đợi", type="primary", disabled=not paths):
        pr = None
        if pages.strip():
            a, _, b = pages.partition("-")
            pr = (int(a), int(b or a))
        ids = [q.submit(p, domain.strip() or "general_medicine", choice, pr,
                        mode="scan_terms" if mode.startswith("Chỉ") else "translate",
                        require_lock=gate and not mode.startswith("Chỉ"), source_lang=lang) for p in paths]
        st.success(f"Đã đưa {len(ids)} tài liệu vào hàng đợi: " + ", ".join(f"#{i}" for i in ids))
        time.sleep(0.6)
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
                                       ("termbase_xlsx", "Termbase (Excel)",
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")):
                    if res.get(k) and Path(res[k]).exists():
                        st.download_button(f"⬇ {label}", Path(res[k]).read_bytes(), file_name=Path(res[k]).name,
                                           mime=mime, key=f"d{k}{j['id']}")
                if j["status"] == "awaiting_termbase":
                    st.caption("→ Kiểm tra & khoá ở mục **Termbase dự án**")
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
    if st.button("🔁 Dựng lại PDF từ dữ liệu hiện tại", type="primary"):
        qid = state.queue().submit(j["pdf_path"], j["domain"], cfg.get("default_profile", "premium"))
        st.success(f"Đã đưa vào hàng đợi #{qid} – các đoạn đã có sẽ được dùng lại, không dịch lại.")


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
def settings_page():
    cfg, db = state.cfg(), state.db()
    page_header("Cấu hình & hệ thống", "Kết nối API, tài nguyên máy, quy ước chuyên ngành, cấu hình")
    from medtrans.scan import tesseract_available
    key_ok = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    kpis([("Claude API key", "Đã cấu hình" if key_ok else "Chưa có", ".env"),
          ("Tesseract OCR", "Sẵn sàng" if tesseract_available() else "Chưa cài", "PDF scan & chữ trong hình"),
          ("Nhân CPU", os.cpu_count() or "?", "OCR & dàn trang song song"),
          ("Hồ sơ mặc định", _plabel(cfg, cfg.get("default_profile", "premium")))])
    if not key_ok:
        st.warning("Chưa có ANTHROPIC_API_KEY. Tạo file `.env` theo `.env.example` rồi khởi động lại.")
    st.subheader("Phần cứng máy này & đề xuất")
    from medtrans.hardware import detect, recommend
    hw = detect()
    rec = recommend(hw)
    gpu = ", ".join(f"{g['name']} ({g['vram_gb']} GB)" for g in hw["gpus"]) or "không phát hiện GPU NVIDIA"
    st.markdown(f"<div class='card'><b>{esc(rec['tier'])}</b><div class='muted'>GPU: {esc(gpu)} · RAM: "
                f"{hw['ram_gb']} GB</div><div style='margin-top:6px'>Model local đề xuất: <b>{esc(rec['local_model'])}"
                f"</b> · Hồ sơ đề xuất: <b>{esc(rec['profile'])}</b></div><div class='muted'>{esc(rec['note'])}</div>"
                "<div class='muted'>Đo tốc độ thật: <code>python -m medtrans hw --save</code></div></div>",
                unsafe_allow_html=True)
    st.subheader("Model chạy local")
    import httpx2
    for name, label in (("local", "Máy chủ model local (Ollama / vLLM / llama.cpp / LM Studio)"),
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
