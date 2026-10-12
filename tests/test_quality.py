"""Kiểm thử: chấm điểm MQM, tự chứng nhận, tự làm giàu thuật ngữ, PDF scan, hồ sơ ngôn ngữ, chuyển đổi CSDL."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample import make  # noqa: E402

from medtrans.config import load_config  # noqa: E402
from medtrans.db import Database  # noqa: E402
from medtrans.languages import get_profile  # noqa: E402
from medtrans.llm import MockLLM  # noqa: E402
from medtrans.translator import Translator, Unit  # noqa: E402


def _translator(tmp_path, llm=None, **over) -> Translator:
    cfg = load_config(overrides={"llm": {"provider": "mock"}, "memory": {"db_path": str(tmp_path / "q.db")},
                                 **over})
    tr = Translator(cfg, llm=llm)
    tr.domain, tr.domains, tr.job_id = "cardiology", ["cardiology", "general_medicine"], "job"
    tr.system_fidelity = []
    return tr


def test_mqm_score():
    src = " ".join(["word"] * 100)
    assert Translator.mqm_score(src, []) == 100
    assert Translator.mqm_score(src, [{"severity": "minor"}]) == 99
    assert Translator.mqm_score(src, [{"severity": "major"}]) == 95
    assert Translator.mqm_score(src, [{"severity": "critical"}]) == 75
    # đoạn ngắn: mẫu số tối thiểu 40 từ
    assert Translator.mqm_score("Heart failure", [{"severity": "minor"}]) == 98


class FixingLLM(MockLLM):
    """Giám khảo tìm 1 lỗi major ở vòng đầu và đưa bản sửa; vòng sau không còn lỗi."""

    def __init__(self):
        super().__init__({})
        self.eval_calls = 0

    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "evaluate":
            self.eval_calls += 1
            segs = payload["segments"]
            if self.eval_calls == 1:
                return {"segments": [{"id": s["id"], "errors": [
                    {"category": "terminology", "severity": "major", "source_span": "heart failure",
                     "target_span": "hỏng tim", "explanation": "sai thuật ngữ", "fix": "suy tim"}],
                    "corrected": "Suy tim là một hội chứng lâm sàng."} for s in segs]}
            return {"segments": [{"id": s["id"], "errors": [], "corrected": ""} for s in segs]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def test_evaluate_applies_fix_and_certifies(tmp_path):
    llm = FixingLLM()
    tr = _translator(tmp_path, llm=llm, quality={"judges": ["clinical"], "certify_score": 97})
    tr.system_translate = []
    tr.system_eval = {"clinical": []}
    u = Unit(id="u1", page=0, role="body", blocks=[], src="Heart failure is a clinical syndrome.", mapping={},
             italic_spans=[], tgt="Hỏng tim là một hội chứng lâm sàng.")
    tr._evaluate([u], {}, rounds=2)
    assert llm.eval_calls == 2
    assert u.tgt == "Suy tim là một hội chứng lâm sàng." and u.score == 100
    tr._finalize([u])
    assert u.status == "certified"
    hit = tr.db.tm_exact(u.src, ["cardiology"])
    assert hit and hit["approved"] == 1


class TermLLM(MockLLM):
    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "extract_terms":
            return {"terms": [{"en": "heart failure with preserved ejection fraction",
                               "vi": "suy tim phân suất tống máu bảo tồn", "category": "disease", "note": ""}]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def _cert_unit(i: int) -> Unit:
    return Unit(id=f"c{i}", page=0, role="body", blocks=[], mapping={}, italic_spans=[], status="certified",
                score=98,
                src=f"Patients with heart failure with preserved ejection fraction need diuretics in case {i}.",
                tgt=f"Bệnh nhân suy tim phân suất tống máu bảo tồn cần thuốc lợi tiểu trong trường hợp {i}.")


def test_term_auto_approved_with_evidence(tmp_path):
    tr = _translator(tmp_path, llm=TermLLM({}))
    need = tr.cfg.get_path("quality.term_min_evidence", 3)
    for i in range(need - 1):                            # chưa đủ bằng chứng → chưa duyệt
        assert tr._enrich_terms([_cert_unit(i)], f"{i}.pdf")["auto_approved"] == 0
    stats = tr._enrich_terms([_cert_unit(need)], "last.pdf")   # cộng dồn qua các tài liệu → đủ ngưỡng
    assert stats["auto_approved"] == 1
    approved = {t["en"]: t for t in tr.db.terms(["cardiology"])}
    assert approved["heart failure with preserved ejection fraction"]["vi"] == "suy tim phân suất tống máu bảo tồn"


class PanelLLM(MockLLM):
    """Hai giám khảo báo cùng một lỗi → chỉ tính một lần, giữ mức nặng hơn."""

    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "evaluate":
            sev = "major" if system == ["clinical"] else "minor"
            return {"segments": [{"id": s["id"], "errors": [
                {"category": "terminology", "severity": sev, "source_span": "x", "target_span": "hỏng tim",
                 "explanation": "", "fix": ""}], "corrected": ""} for s in payload["segments"]]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def test_judge_panel_merges_errors(tmp_path):
    tr = _translator(tmp_path, llm=PanelLLM({}), quality={"judges": ["clinical", "linguistic"]})
    tr.system_translate = []
    tr.system_eval = {"clinical": ["clinical"], "linguistic": ["linguistic"]}
    u = Unit(id="u", page=0, role="body", blocks=[], src="Heart failure.", mapping={}, italic_spans=[],
             tgt="Hỏng tim.")
    tr._evaluate([u], {}, rounds=1)
    assert len(u.mqm) == 1 and u.mqm[0]["severity"] == "major" and u.score == 88
    tr._finalize([u])
    assert u.status == "done"  # lỗi major → không được chứng nhận


def test_estimate_has_time_and_cost(tmp_path):
    from medtrans.translator import estimate
    est = estimate(make(tmp_path / "e.pdf"), cfg=load_config(), db=Database(tmp_path / "e.db"))
    assert est["estimated_time_low"] and est["estimated_cost_usd_high"] > 0 and est["a4_equivalent_pages"] > 0


def test_web_term_trust_rules(tmp_path):
    tr = _translator(tmp_path)
    good = {"confidence": 0.9, "sources": ["https://kcb.vn/a", "https://example.com/b"]}
    assert tr._web_term_trusted(good)
    assert not tr._web_term_trusted({**good, "confidence": 0.6})
    assert not tr._web_term_trusted({"confidence": 0.95, "sources": ["https://a.com", "https://b.com"]})
    assert not tr._web_term_trusted({"confidence": 0.95, "sources": ["https://kcb.vn/a"]})


def test_language_profile():
    assert get_profile("en").tesseract == "eng"
    with pytest.raises(ValueError):
        get_profile("xx")


def test_legacy_db_migration(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE glossary (id INTEGER PRIMARY KEY AUTOINCREMENT, en TEXT, en_norm TEXT, vi TEXT,
          domain TEXT, category TEXT, note TEXT, keep_original INTEGER, gloss_first INTEGER, case_sensitive INTEGER,
          priority INTEGER, source TEXT, source_url TEXT, status TEXT, created_at REAL, updated_at REAL,
          UNIQUE(en_norm, domain));
        CREATE INDEX idx_gloss_status ON glossary(status);
        CREATE TABLE tm (id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT, src_norm TEXT, src_hash TEXT, tgt TEXT,
          domain TEXT, doc_name TEXT, role TEXT, quality INTEGER, approved INTEGER, created_at REAL,
          UNIQUE(src_hash, domain));
        INSERT INTO glossary (en, en_norm, vi, domain, status) VALUES ('stroke', 'stroke', 'đột quỵ', 'g', 'approved');
    """)
    con.commit()
    con.close()
    db = Database(path)
    t = db.terms(["g"])[0]
    assert t["vi"] == "đột quỵ" and t["src_lang"] == "en" and t["evidence"] == 0


# ---------------------------------------------------------------- PDF scan
def _tesseract() -> bool:
    from medtrans.scan import tesseract_available
    return tesseract_available()


@pytest.mark.skipif(not _tesseract(), reason="cần Tesseract OCR")
def test_scanned_pdf_pipeline(tmp_path):
    src = pymupdf.open(make(tmp_path / "s.pdf"))
    out = pymupdf.open()
    for pg in src:
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, stream=pg.get_pixmap(dpi=200).tobytes("png"))
    scanned = tmp_path / "scanned.pdf"
    out.save(scanned)

    from medtrans.pdf_extract import extract
    pages = extract(scanned)
    assert all(p.scanned for p in pages)
    blocks = pages[0].blocks
    first = next(b for b in blocks if b.plain.startswith("Heart failure is"))
    # đoạn bị Tesseract tách vẫn đúng thứ tự & được nối câu
    assert "should be measured by echocardiography" in first.plain
    assert first.chain_next and any(b.id == first.chain_next and b.plain.startswith("dose") for b in blocks)

    tr = Translator(load_config(overrides={"llm": {"provider": "mock"},
                                           "memory": {"db_path": str(tmp_path / "s.db")}}))
    res = tr.run(scanned, out_dir=tmp_path)
    assert res["scanned_pages"] == 2
    text = pymupdf.open(res["output_pdf"])[0].get_text()
    assert "[VI]" in text


class ProofLLM(MockLLM):
    """Người đọc morat phát hiện một lỗi chính tả ở trang 1 (chỉ ở lần đọc đầu)."""

    def __init__(self):
        super().__init__({})
        self.proof_calls = 0

    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "proof":
            self.proof_calls += 1
            if payload["page"] == 0 and self.proof_calls <= 2:
                return {"issues": [{"type": "typo", "severity": "minor", "quote": "[VI] Key points",
                                    "correction": "Điểm chính", "description": "tiêu đề chưa dịch"}]}
            return {"issues": []}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def test_proof_fix_and_relayout(tmp_path):
    llm = ProofLLM()
    cfg = load_config(overrides={"llm": {"provider": "mock"}, "memory": {"db_path": str(tmp_path / "p.db")}})
    res = Translator(cfg, llm=llm).run(make(tmp_path / "p.pdf"), out_dir=tmp_path)
    text = pymupdf.open(res["output_pdf"])[0].get_text()
    assert "Điểm chính" in text and "Key points" not in text
    assert res["proof"]["fixed_text"] == 1


# ---------------------------------------------------------------- chế tài trung thành
def test_fidelity_enforcement_missing_sentence_and_order():
    from medtrans.fidelity import enforce
    src = "Heart failure is common. Beta-blockers are not recommended. Measure BNP."
    tgt = "Đo BNP. Suy tim là bệnh thường gặp."
    # kiểm toán viên "quên" câu 2 và câu 3 nằm trước câu 1 trong bản dịch
    res = {"sentences": [{"n": 1, "target_span": "Suy tim là bệnh thường gặp", "verdict": "ok"},
                         {"n": 3, "target_span": "Đo BNP", "verdict": "ok"}], "additions": []}
    errs = enforce(src, tgt, res)
    kinds = {(e["category"], e["severity"]) for e in errs}
    assert ("accuracy_omission", "critical") in kinds          # câu 2 không được ánh xạ → coi là bỏ sót
    assert any("trình tự" in e["explanation"] for e in errs)    # sai trình tự


def test_fidelity_blocks_certification(tmp_path):
    class OmitLLM(MockLLM):
        def json_call(self, *, task, system, user, schema, effort="high", payload=None):
            if task == "fidelity":
                return {"segments": [{"id": s["id"], "sentences": [], "additions": ["(chú thích tự thêm)"]}
                                     for s in payload["segments"]]}
            return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort,
                                     payload=payload)

    tr = _translator(tmp_path, llm=OmitLLM({}), quality={"judges": ["clinical"]})
    tr.system_translate = []
    tr.system_eval = {"clinical": []}
    u = Unit(id="u", page=0, role="body", blocks=[], src="Heart failure is common. Measure BNP.", mapping={},
             italic_spans=[], tgt="Suy tim là bệnh thường gặp. Đo BNP.")
    tr._evaluate([u], {}, rounds=1)
    tr._finalize([u])
    assert u.status == "needs_review"
    assert any(e["judge"] == "fidelity" for e in u.mqm)


# ---------------------------------------------------------------- termbase dự án: quét → kiểm tra → khoá → dịch
class TermScanLLM(MockLLM):
    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "termprep":
            return {"terms": [{"en": "decompensated heart failure", "vi": "suy tim mất bù", "category": "disease",
                               "confidence": 0.95, "note": ""}]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def test_termbase_scan_review_lock_flow(tmp_path):
    from medtrans.termbase import lock, read_xlsx
    cfg = load_config(overrides={"llm": {"provider": "mock"}, "memory": {"db_path": str(tmp_path / "t.db")},
                                 "terminology": {"require_lock": True}})
    pdf = make(tmp_path / "t.pdf")
    tr = Translator(cfg, llm=TermScanLLM({}))
    from medtrans.glossary import import_file
    import_file(tr.db, Path(__file__).resolve().parent.parent / "data" / "glossary_seed.csv")
    res = tr.run(pdf, out_dir=tmp_path)                      # chốt chặn: chỉ quét, chưa dịch
    assert res["status"] == "awaiting_termbase" and Path(res["termbase_xlsx"]).exists()
    rows = read_xlsx(res["termbase_xlsx"])
    by_en = {r["en"]: r for r in rows}
    assert "decompensated heart failure" in by_en and "heart failure" in by_en   # đề xuất mới + kho chuẩn
    # chuyên gia sửa cách dịch và loại một thuật ngữ
    by_en["decompensated heart failure"]["vi_final"] = "suy tim mất bù cấp"
    by_en["heart failure"]["status"] = "Loại"
    st = lock(tr.db, res["job_id"], rows, "general_medicine")
    assert st["locked"] >= 1 and st["rejected"] == 1
    out = Translator(cfg, db=tr.db, llm=TermScanLLM({})).run(pdf, out_dir=tmp_path)   # giờ mới dịch chính thức
    assert Path(out["output_pdf"]).exists()
    t = {x["en"]: x for x in tr.db.terms(["general_medicine"])}
    assert t["decompensated heart failure"]["vi"] == "suy tim mất bù cấp"


# ---------------------------------------------------------------- hồ sơ, bản thô → nâng cấp, phân tích, hiệu chuẩn
def test_draft_then_upgrade_reuses_draft(tmp_path):
    from medtrans.config import apply_profile

    class CountLLM(MockLLM):
        def __init__(self):
            super().__init__({})
            self.translate_calls = 0

        def json_call(self, *, task, system, user, schema, effort="high", payload=None):
            if task == "translate":
                self.translate_calls += 1
            return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort,
                                     payload=payload)

    base = load_config(overrides={"llm": {"provider": "mock"}, "memory": {"db_path": str(tmp_path / "d.db")}})
    pdf = make(tmp_path / "d.pdf")
    l1 = CountLLM()
    r1 = Translator(apply_profile(base, "draft"), llm=l1).run(pdf, out_dir=tmp_path)
    assert l1.translate_calls >= 1 and r1["certified"] == 0
    l2 = CountLLM()
    tr = Translator(apply_profile(base, "premium"), llm=l2)
    tr.run(pdf, out_dir=tmp_path)
    text_translate = l2.translate_calls
    assert text_translate <= 1   # văn bản dùng lại bản thô; chỉ chữ trong hình (mới) có thể cần dịch


def test_analysis_bands_and_repetitions(tmp_path):
    from medtrans.analysis import analyze, export_xlsx
    db = Database(tmp_path / "a.db")
    pdf = make(tmp_path / "a.pdf")
    db.tm_add("Treatment", "Điều trị", "general_medicine", quality=99, approved=True)
    res = analyze(pdf, load_config(), db)
    bands = {b["key"]: b for b in res["bands"]}
    assert bands["tm100"]["segments"] == 1
    assert res["totals"]["words"] > 100 and res["profiles"]
    assert export_xlsx(res, tmp_path / "a.xlsx").exists()


def test_calibration_records_probability(tmp_path):
    from medtrans.calibrate import calibrate, wilson
    lo, hi = wilson(18, 20)
    assert 0.65 < lo < 0.75 and 0.95 < hi <= 1.0
    db = Database(tmp_path / "c.db")
    cfg = load_config(overrides={"llm": {"provider": "mock"}})
    rows = calibrate(make(tmp_path / "c.pdf"), cfg, db, ["economy", "premium"], page_range=(1, 1),
                     llm_factory=lambda c: MockLLM({}))
    assert len(rows) == 2 and all(0 <= r["pass_rate"] <= 100 for r in rows)
    assert db.query("SELECT COUNT(*) n FROM calibration")[0]["n"] == 2


def test_job_queue_pause_cancel_and_complete(tmp_path):
    from medtrans.jobs import JobQueue
    db = Database(tmp_path / "q.db")
    cfg = load_config(overrides={"llm": {"provider": "mock"}, "output": {"dir": str(tmp_path / "out")}})
    q = JobQueue(cfg, db, llm_factory=lambda c: MockLLM({}), autostart=False)
    pdf = make(tmp_path / "q.pdf")
    a = q.submit(pdf, "general_medicine", "economy")
    b = q.submit(pdf, "general_medicine", "premium")
    q.control(b, "cancel")                       # huỷ khi còn chờ
    q.run_pending()
    assert q.get(a)["status"] == "done" and Path(json.loads(q.get(a)["result_json"])["output_pdf"]).exists()
    assert q.get(b)["status"] == "cancelled"
    c = q.submit(pdf, "general_medicine", "premium", mode="scan_terms")
    q.run_pending()
    assert q.get(c)["status"] == "awaiting_termbase"
