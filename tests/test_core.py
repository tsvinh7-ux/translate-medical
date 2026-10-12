"""Kiểm thử các thành phần không cần API: kiểm tra tự động, quy tắc giữ nguyên, thuật ngữ, TM, trích xuất, pipeline mock."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample import make  # noqa: E402

from medtrans.config import load_config  # noqa: E402
from medtrans.db import Database  # noqa: E402
from medtrans.glossary import TermMatcher, import_file  # noqa: E402
from medtrans.pdf_extract import extract  # noqa: E402
from medtrans.rules import load_rules, must_keep_tokens, protect, restore  # noqa: E402
from medtrans.tm import export_tmx, import_tmx  # noqa: E402
from medtrans.verify import check, has_errors, numbers_en, numbers_vi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules()


def codes(issues):
    return {i.code for i in issues}


# ---------------------------------------------------------------- verify
def test_numbers_vi_and_en_agree():
    assert numbers_en("1,000 patients; 0.5 mg; Figure 3.1") == numbers_vi("1.000 bệnh nhân; 0,5 mg; Hình 3.1", "vi")


def test_dose_error_detected():
    src = "Give furosemide 40 mg IV, then 0.5 mg/kg."
    good = "Dùng furosemid 40 mg tiêm tĩnh mạch, sau đó 0,5 mg/kg."
    bad = "Dùng furosemid 4 mg tiêm tĩnh mạch, sau đó 0,5 g/kg."
    assert not has_errors(check(src, good, rules=RULES))
    c = codes(check(src, bad, rules=RULES))
    assert "number_missing" in c and "unit_mismatch" in c


def test_negation_lost():
    src = "Beta-blockers are not recommended in acute heart failure."
    assert "negation" in codes(check(src, "Thuốc chẹn beta được khuyến cáo trong suy tim cấp.", rules=RULES))
    assert "negation" not in codes(check(src, "Không khuyến cáo dùng thuốc chẹn beta trong suy tim cấp.",
                                         rules=RULES))


def test_untranslated_english_flagged():
    src = "The patient should be treated with antibiotics for the infection."
    tgt = "Bệnh nhân should be treated with kháng sinh for the nhiễm khuẩn."
    assert "untranslated" in codes(check(src, tgt, rules=RULES))


def test_placeholders_and_keep_tokens():
    src = "See https://www.who.int/guidelines for HbA1c and ECG targets [12]."
    masked, mapping = protect(src, RULES)
    assert "https://" not in masked and len(mapping) == 1
    key = next(iter(mapping))
    tgt_ok = f"Xem {key} về mục tiêu HbA1c và ECG [12]."
    assert not check(masked, tgt_ok, rules=RULES, placeholders=mapping)
    assert restore(tgt_ok, mapping).startswith("Xem https://www.who.int/guidelines")
    issues = check(masked, "Xem về mục tiêu hemoglobin và điện tâm đồ.", rules=RULES, placeholders=mapping)
    assert {"placeholder", "keep_missing"} <= codes(issues)


def test_must_keep_skips_all_caps_heading():
    assert must_keep_tokens("CHAPTER THREE HEART FAILURE", RULES) == []
    toks = must_keep_tokens("Measure BNP, HbA1c and CD4+ counts; NaHCO3 and TNF-α.", RULES)
    for t in ("BNP", "HbA1c", "NaHCO3"):
        assert t in toks


# ---------------------------------------------------------------- glossary / TM
@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    import_file(d, ROOT / "data" / "glossary_seed.csv")
    return d


def test_glossary_longest_match_and_plural(db):
    m = TermMatcher(db.terms())
    found = {t["en"] for t in m.find("Patients with acute coronary syndromes and left ventricular ejection fraction")}
    assert "acute coronary syndrome" in found
    assert "left ventricular ejection fraction" in found
    assert "ejection fraction" not in found  # cụm dài hơn được ưu tiên


def test_glossary_check(db):
    m = TermMatcher(db.terms())
    src = "Patients with hypertension."
    terms = m.find(src)
    assert "glossary" in codes(check(src, "Bệnh nhân cao huyết áp.", rules=RULES, glossary_terms=terms))
    assert "glossary" not in codes(check(src, "Bệnh nhân tăng huyết áp.", rules=RULES, glossary_terms=terms))


def test_candidate_never_overrides_approved(db):
    db.upsert_term("hypertension", "cao huyết áp", status="candidate", source="web")
    t = [x for x in db.terms() if x["en"] == "hypertension"][0]
    assert t["vi"] == "tăng huyết áp"


def test_tm_roundtrip(db, tmp_path):
    db.tm_add("Heart failure is common.", "Suy tim là bệnh thường gặp.", "general_medicine", quality=95)
    assert db.tm_exact("heart  failure is COMMON.", ["general_medicine"])["tgt"] == "Suy tim là bệnh thường gặp."
    assert db.tm_candidates("Heart failure is very common in elderly", ["general_medicine"])
    path = tmp_path / "x.tmx"
    assert export_tmx(db, path) == 1
    db2 = Database(tmp_path / "t2.db")
    assert import_tmx(db2, path) == 1


# ---------------------------------------------------------------- PDF
@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    return make(tmp_path_factory.mktemp("pdf") / "sample.pdf")


def test_extract_roles_and_order(sample_pdf):
    pages = extract(sample_pdf)
    p0 = pages[0]
    role_of = {b.plain: b.role for b in p0.blocks}
    assert role_of["Chapter 3. Heart Failure"] == "heading"
    assert any(r == "caption" for r in role_of.values())
    texts = [b.plain for b in p0.blocks]
    assert texts.index(next(t for t in texts if t.startswith("Heart failure is"))) < \
        texts.index(next(t for t in texts if t.startswith("Beta-blockers")))
    assert p0.images
    refs = [b for b in pages[1].blocks if b.role == "reference"]
    assert refs and refs[0].keep


def test_mock_pipeline(sample_pdf, tmp_path):
    from medtrans.translator import Translator
    cfg = load_config(overrides={"llm": {"provider": "mock"},
                                 "memory": {"db_path": str(tmp_path / "m.db")}})
    tr = Translator(cfg)
    import_file(tr.db, ROOT / "data" / "glossary_seed.csv")
    res = tr.run(sample_pdf, out_dir=tmp_path)
    assert Path(res["output_pdf"]).exists() and Path(res["report"]).exists()
    text = pymupdf.open(res["output_pdf"])[0].get_text()
    assert "[VI]" in text
    assert res["render"]["overflow"] == 0
    # chạy lại: dùng kết quả đã lưu, không gọi dịch lại
    calls_before = tr.llm.usage.calls
    tr2 = Translator(cfg, db=tr.db, llm=tr.llm)
    tr2.run(sample_pdf, out_dir=tmp_path)
    assert tr.llm.usage.calls - calls_before <= 3  # chỉ OCR ảnh / trích thuật ngữ, không dịch lại văn bản
