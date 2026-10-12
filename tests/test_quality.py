"""Kiểm thử: chấm điểm MQM, tự chứng nhận, tự làm giàu thuật ngữ, PDF scan, hồ sơ ngôn ngữ, chuyển đổi CSDL."""
from __future__ import annotations

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
    tr = _translator(tmp_path, llm=llm)
    tr.system_eval = tr.system_translate = []
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
    stats = tr._enrich_terms([_cert_unit(1)], "a.pdf")   # 1 bằng chứng < ngưỡng 2
    assert stats["auto_approved"] == 0
    stats = tr._enrich_terms([_cert_unit(2)], "b.pdf")   # cộng dồn qua tài liệu → 2
    assert stats["auto_approved"] == 1
    approved = {t["en"]: t for t in tr.db.terms(["cardiology"])}
    assert approved["heart failure with preserved ejection fraction"]["vi"] == "suy tim phân suất tống máu bảo tồn"


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
