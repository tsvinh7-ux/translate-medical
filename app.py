"""Giao diện web chạy trên máy (localhost): streamlit run app.py  hoặc  python -m medtrans ui"""
from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from medtrans.config import ROOT, load_config
from medtrans.db import Database
from medtrans.glossary import export_csv, import_file

from medtrans.branding import brand, css, logo_path

cfg = load_config()
B = brand(cfg)
st.set_page_config(page_title=B["app_title"], page_icon="🩺", layout="wide")
st.markdown(css(cfg), unsafe_allow_html=True)
_logo = logo_path(cfg)
if _logo:
    st.logo(str(_logo))
DB_PATH = cfg.resolve(cfg.get_path("memory.db_path", "workspace/medtrans.db"))
UPLOAD_DIR = cfg.resolve("workspace/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@st.cache_resource
def get_db() -> Database:
    db = Database(DB_PATH)
    if not db.query("SELECT 1 FROM glossary LIMIT 1"):
        import_file(db, ROOT / "data" / "glossary_seed.csv", overwrite=False)
    return db


db = get_db()

st.markdown(f'<div class="brand-bar"><span class="brand-name">{B["name"]}</span>'
            f'<span class="brand-sub">{B["app_title"]}</span></div>', unsafe_allow_html=True)

STAGES = [(0.02, "Phân tích bố cục & OCR trang scan"), (0.025, "Đọc tổng quan tài liệu"),
          (0.05, "Chuẩn bị thuật ngữ toàn văn"),
          (0.8, "Dịch → Hiệu đính chuyên môn → Biên tập ngôn ngữ → Hội đồng giám khảo MQM"),
          (0.84, "Dịch chữ trong hình"), (0.88, "Biên tập toàn văn"), (0.9, "Dàn trang"),
          (0.95, "Đọc morat & sửa morat"), (1.0, "Làm giàu thuật ngữ & bộ nhớ dịch, báo cáo")]


def stage_html(frac: float) -> str:
    out, prev = [], 0.0
    for end, name in STAGES:
        cls = "done" if frac >= end else ("now" if frac >= prev else "todo")
        out.append(f'<div class="stage {cls}">{"✓" if cls == "done" else ("▶" if cls == "now" else "○")} {name}</div>')
        prev = end
    return "".join(out)
key_ok = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
if not key_ok and cfg.get_path("llm.provider") != "mock":
    st.warning("Chưa có ANTHROPIC_API_KEY. Tạo file `.env` (xem `.env.example`) rồi khởi động lại.")

tab_tr, tab_rv, tab_gl, tab_tm, tab_cfg = st.tabs(
    ["📄 Dịch tài liệu", "✍️ Duyệt bản dịch", "📚 Thuật ngữ", "🧠 Bộ nhớ dịch", "⚙️ Cấu hình"])

# =============================================================== DỊCH
with tab_tr:
    up = st.file_uploader("Chọn file PDF cần dịch", type=["pdf"])
    from medtrans.languages import PROFILES
    c0, c1, c2, c3 = st.columns(4)
    src_lang = c0.selectbox("Ngôn ngữ nguồn → tiếng Việt", list(PROFILES),
                            format_func=lambda c: f"{PROFILES[c].name_vi} ({c})",
                            help="Hiện hoàn thiện Anh → Việt. Ngôn ngữ khác sẽ được bổ sung dạng module.")
    domain = c1.text_input("Chuyên ngành (domain)", cfg.get_path("translation.domain", "general_medicine"),
                           help="Ví dụ: cardiology, oncology, pharmacology, pediatrics... Thuật ngữ & bộ nhớ dịch "
                                "được lưu theo chuyên ngành để dùng lại.")
    pages = c2.text_input("Trang cần dịch (để trống = tất cả)", "", placeholder="ví dụ 1-20")
    mock = c3.checkbox("Chạy thử (không gọi API)", value=cfg.get_path("llm.provider") == "mock")
    if up:
        pdf_path = UPLOAD_DIR / up.name
        pdf_path.write_bytes(up.getbuffer())
        b1, b2 = st.columns(2)
        if b1.button("💰 Ước tính chi phí & thời gian"):
            from medtrans.translator import estimate
            st.json(estimate(pdf_path, cfg.get_path("llm.model"), cfg=cfg, db=db))
        if b2.button("🚀 Bắt đầu dịch", type="primary"):
            from medtrans.translator import Translator
            over = {"translation": {"source_lang": src_lang}}
            if mock:
                over["llm"] = {"provider": "mock"}
            run_cfg = load_config(overrides=over)
            bar = st.progress(0.0, "Bắt đầu...")
            stage_box = st.empty()

            def on_progress(f, m):
                bar.progress(min(1.0, f), m)
                stage_box.markdown(stage_html(f), unsafe_allow_html=True)

            pr = None
            if pages.strip():
                a, _, b = pages.partition("-")
                pr = (int(a), int(b or a))
            tr = Translator(run_cfg, db=db, progress=on_progress)
            try:
                res = tr.run(pdf_path, domain=domain.strip() or None, page_range=pr)
                st.session_state["last_result"] = res
                st.success("Hoàn tất!")
            except Exception as e:
                st.exception(e)
    res = st.session_state.get("last_result")
    if res:
        k = st.columns(6)
        k[0].metric("Số đoạn", res["segments"])
        k[1].metric("Điểm MQM TB", res["avg_score"])
        k[2].metric("Đạt chuẩn", res.get("certified", 0))
        k[3].metric("Còn lỗi nặng", res["needs_review"])
        k[4].metric("Dùng lại TM", res["from_tm"])
        k[5].metric("Chi phí (USD)", res["usage"]["estimated_cost_usd"])
        te = res.get("term_enrichment") or {}
        if te:
            st.caption(f"Tự làm giàu thuật ngữ: {te.get('proposed', 0)} đề xuất, {te.get('auto_approved', 0)} tự duyệt, "
                       f"{te.get('rejected', 0)} bị loại/sửa. Trang scan: {res.get('scanned_pages', 0)}.")
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Tải PDF tiếng Việt", Path(res["output_pdf"]).read_bytes(),
                           file_name=Path(res["output_pdf"]).name, mime="application/pdf")
        if res.get("report"):
            d2.download_button("⬇️ Tải báo cáo song ngữ (HTML)", Path(res["report"]).read_bytes(),
                               file_name=Path(res["report"]).name, mime="text/html")
        with st.expander("Chi tiết"):
            st.json(res)

# =============================================================== DUYỆT
with tab_rv:
    jobs = db.query("SELECT job_id, pdf_path, domain, status, updated_at FROM jobs ORDER BY updated_at DESC")
    if not jobs:
        st.info("Chưa có tài liệu nào được dịch.")
    else:
        labels = {f"{Path(j['pdf_path']).name} [{j['domain']}] – {j['status']}": j for j in jobs}
        job = labels[st.selectbox("Tài liệu", list(labels))]
        st.caption("Không bắt buộc: hệ thống đã tự chấm MQM và tự chứng nhận. Tab này để xem/sửa thêm nếu bạn muốn.")
        only_bad = st.checkbox("Chỉ hiện đoạn chưa đạt chuẩn", value=True)
        segs = sorted(db.segments(job["job_id"]).values(), key=lambda s: (s["page"], s["seg_id"]))
        if only_bad:
            segs = [s for s in segs if s["status"] not in ("certified", "tm")]
        st.caption(f"{len(segs)} đoạn. Giữ nguyên các mã ⟦n⟧ (ký hiệu/URL/công thức) và ⟦¶⟧ (ngắt cột/trang). "
                   "Lưu xong bấm 'Dựng lại PDF' — không tốn token.")
        for s in segs[:200]:
            with st.expander(f"Trang {s['page'] + 1} · {s['role']} · điểm {s['score']} · {s['status']} · {s['seg_id']}"):
                st.markdown("**Bản gốc**")
                st.write(s["src"])
                for i in s["issues"]:
                    (st.error if i.get("severity") == "error" else st.caption)(i.get("message", ""))
                new = st.text_area("Bản dịch", s["tgt"], key=f"t_{s['seg_id']}", height=150)
                if st.button("💾 Lưu & duyệt", key=f"b_{s['seg_id']}"):
                    db.segment_save(job["job_id"], s["seg_id"], page=s["page"], kind=s["kind"], role=s["role"],
                                    src=s["src"], tgt=new, status="done", score=100,
                                    issues=[{"severity": "info", "code": "human", "message": "Đã duyệt tay"}])
                    db.tm_add(s["src"], new, job["domain"], doc_name=job["job_id"], role=s["role"], quality=100,
                              approved=True)
                    st.success("Đã lưu vào bộ nhớ dịch (đánh dấu đã duyệt).")
        if st.button("🔁 Dựng lại PDF từ bản đã duyệt"):
            from medtrans.translator import Translator
            bar = st.progress(0.0)
            tr = Translator(cfg, db=db, progress=lambda f, m: bar.progress(min(1.0, f), m))
            st.session_state["last_result"] = tr.run(job["pdf_path"], domain=job["domain"])
            st.success("Đã dựng lại. Tải file ở tab 'Dịch tài liệu'.")

# =============================================================== THUẬT NGỮ
with tab_gl:
    st.subheader("Nhập thuật ngữ từ file")
    st.caption("CSV / Excel (.xlsx) / TBX. Cột bắt buộc: `en`, `vi`. Tuỳ chọn: `domain, category, note, "
               "keep_original, gloss_first, case_sensitive, priority, source_url`. Mẫu: data/glossary_template.csv")
    gf = st.file_uploader("File thuật ngữ", type=["csv", "xlsx", "tbx", "txt"], key="gl_up")
    gdom = st.text_input("Chuyên ngành mặc định cho file này", cfg.get_path("translation.domain"), key="gl_dom")
    if gf and st.button("Nhập"):
        tmp = Path(tempfile.mkdtemp()) / gf.name
        tmp.write_bytes(gf.getbuffer())
        st.success(f"Đã nhập {import_file(db, tmp, default_domain=gdom)} thuật ngữ.")

    with st.form("add_term"):
        st.subheader("Thêm nhanh")
        a1, a2, a3 = st.columns(3)
        en = a1.text_input("Tiếng Anh")
        vi = a2.text_input("Tiếng Việt")
        dom = a3.text_input("Chuyên ngành", cfg.get_path("translation.domain"))
        note = st.text_input("Ghi chú ngữ cảnh")
        keep = st.checkbox("Giữ nguyên tiếng Anh")
        if st.form_submit_button("Thêm") and en:
            db.upsert_term(en, vi, dom, note=note, keep_original=keep)
            st.success("Đã thêm.")

    st.subheader("Thuật ngữ đề xuất (đang tích luỹ bằng chứng)")
    st.caption("Hệ thống TỰ DUYỆT khi thuật ngữ được dùng nhất quán trong ≥ "
               f"{cfg.get_path('quality.term_min_evidence', 2)} đoạn đạt chuẩn MQM và qua kiểm định độc lập; "
               "thuật ngữ tra web được tự duyệt khi có nguồn uy tín. Bạn vẫn có thể duyệt/loại tay.")
    cand = db.terms(status="candidate")
    if cand:
        df = pd.DataFrame(cand)[["id", "en", "vi", "domain", "evidence", "source", "note", "source_url"]]
        df.insert(0, "duyệt", False)
        df.insert(1, "loại", False)
        ed = st.data_editor(df, hide_index=True, width="stretch", key="cand_ed",
                            column_config={"id": None})
        if st.button("Áp dụng"):
            for _, r in ed.iterrows():
                if r["duyệt"]:
                    db.upsert_term(r["en"], r["vi"], r["domain"], note=r["note"], source=r["source"],
                                   source_url=r["source_url"] or "", status="approved")
                elif r["loại"]:
                    db.set_term_status(int(r["id"]), "rejected")
            st.rerun()
    else:
        st.caption("Không có.")

    st.subheader("Thuật ngữ đã duyệt")
    appr = db.terms(status="approved")
    q = st.text_input("Tìm", "")
    rows = [t for t in appr if q.lower() in (t["en"] + " " + t["vi"]).lower()] if q else appr
    st.dataframe(pd.DataFrame(rows)[["en", "vi", "domain", "category", "evidence", "source", "note"]]
                 if rows else pd.DataFrame(),
                 width="stretch", hide_index=True)
    buf = Path(tempfile.mkdtemp()) / "glossary_export.csv"
    export_csv(db, buf)
    st.download_button("⬇️ Xuất toàn bộ thuật ngữ (CSV)", buf.read_bytes(), file_name="glossary_export.csv")

# =============================================================== TM
with tab_tm:
    from medtrans import tm as tm_mod
    st.metric("Số cặp câu trong bộ nhớ dịch", db.tm_stats()["segments"])
    st.json(db.tm_stats())
    st.subheader("Nhập bản dịch có sẵn (TMX / CSV / Excel song ngữ)")
    st.caption("Ví dụ: bản dịch sách cũ đã được biên tập. Câu khớp 100% sẽ được dùng lại không tốn token; "
               "câu tương tự được đưa vào làm tham khảo để AI dịch nhất quán văn phong.")
    tf = st.file_uploader("File", type=["tmx", "csv", "xlsx"], key="tm_up")
    tdom = st.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="tm_dom")
    if tf and st.button("Nhập TM"):
        tmp = Path(tempfile.mkdtemp()) / tf.name
        tmp.write_bytes(tf.getbuffer())
        n = tm_mod.import_tmx(db, tmp, tdom) if tmp.suffix.lower() == ".tmx" else \
            tm_mod.import_bilingual_table(db, tmp, tdom)
        st.success(f"Đã nhập {n} cặp câu.")
    out = Path(tempfile.mkdtemp()) / "medtrans_memory.tmx"
    n = tm_mod.export_tmx(db, out, min_quality=95)
    st.download_button(f"⬇️ Xuất TMX ({n} cặp câu đạt chuẩn ≥ 95)", out.read_bytes(), file_name="medtrans_memory.tmx")

# =============================================================== CẤU HÌNH
with tab_cfg:
    st.subheader("Quy ước văn phong theo chuyên ngành")
    st.caption("Ghi chú riêng cho chuyên ngành (ví dụ cách gọi tên, văn phong NXB, quy tắc viết hoa...). "
               "Được đưa vào mọi lần dịch thuộc chuyên ngành này.")
    dn = st.text_input("Chuyên ngành", cfg.get_path("translation.domain"), key="dn_dom")
    notes = st.text_area("Quy ước", db.domain_notes(dn), height=200)
    if st.button("Lưu quy ước"):
        db.set_domain_notes(dn, notes)
        st.success("Đã lưu.")
    st.subheader("config.yaml hiện tại")
    st.code((ROOT / "config.yaml").read_text(encoding="utf-8"), language="yaml")
    st.subheader("Quy tắc giữ nguyên (data/preserve_rules.yaml)")
    st.code((ROOT / "data" / "preserve_rules.yaml").read_text(encoding="utf-8"), language="yaml")
