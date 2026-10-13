"""Gói chuẩn: 2 phương thức (local + API hỗ trợ | API hoàn toàn) × 5 phạm vi công việc."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from make_sample import make  # noqa: E402

from medtrans import plans  # noqa: E402
from medtrans.config import apply_profile, load_config  # noqa: E402
from medtrans.jobs import JobQueue  # noqa: E402
from medtrans.db import Database  # noqa: E402
from medtrans.llm import MockLLM  # noqa: E402
from medtrans.translator import Translator  # noqa: E402

COUNTS = {"pages": 300, "chars": 900_000, "weighted_chars": 800_000, "scanned": 10, "images": 40}


def test_scope_flags_and_bases():
    cfg = load_config()
    d = apply_profile(cfg, "plan:api:draft")
    assert d["plan"]["base_profile"] == "draft" and d.get_path("workflow.draft")
    assert not d.get_path("workflow.edit") and not d.get_path("quality.independent_eval")
    e = apply_profile(cfg, "plan:api:edit")
    assert e.get_path("workflow.edit") and not e.get_path("workflow.revise") and not e.get_path("proof.vision")
    r = apply_profile(cfg, "plan:local:revise")
    assert r.get_path("llm.provider") == "local" and r.get_path("workflow.revise") and r.get_path("escalation.enabled")
    p = apply_profile(cfg, "plan:api:publish:w32")
    assert p.get_path("proof.vision") and p.get_path("translation.workers") == 32
    assert plans.plan_label("plan:api:publish:w32") == "API · Trọn gói xuất bản · 32 luồng"
    assert plans.mode_for("plan:local:termbase") == "scan_terms" and plans.mode_for("plan:api:edit") == "translate"
    with pytest.raises(ValueError):
        apply_profile(cfg, "plan:cloud:publish")


def test_pipeline_lists_morat_only_for_publish():
    cfg = load_config()
    names = lambda n: [a for a, _ in plans.pipeline(apply_profile(cfg, n))]  # noqa: E731
    assert any("morat" in a for a in names("plan:api:publish"))
    assert not any("morat" in a for a in names("plan:api:revise"))
    assert any("Hiệu đính" in a for a in names("plan:local:revise"))
    assert not any("Hiệu đính" in a for a in names("plan:local:edit"))
    tb = plans.pipeline(apply_profile(cfg, "plan:local:termbase"))
    assert tb[-1][0].startswith("Xuất termbase") and not any(a.startswith("Dịch theo") for a, _ in tb)
    assert dict(plans.pipeline(apply_profile(cfg, "plan:local:publish")))["Đọc morat trên trang & sửa morat"] == \
        "Claude API"                                                     # local: morat hình ảnh vẫn do Claude


def test_matrix_costs_grow_with_scope_and_local_is_cheaper():
    m = plans.matrix(load_config(), COUNTS)
    api = [m[("api", s)]["estimated_cost_usd_high"] for s in ("edit", "revise", "publish")]
    assert api == sorted(api) and api[0] > 0
    assert m[("api", "draft")]["estimated_cost_usd_high"] < api[0]
    for s in ("edit", "revise", "publish"):
        assert m[("local", s)]["estimated_cost_usd_high"] < m[("api", s)]["estimated_cost_usd_high"]
    assert m[("local", "draft")]["estimated_cost_usd_high"] == 0
    assert 0 < m[("api", "termbase")]["estimated_cost_usd_high"] < api[0]


def test_queue_runs_plan_and_draft_is_not_certified(tmp_path):
    db = Database(tmp_path / "q.db")
    cfg = load_config(overrides={"memory": {"db_path": str(tmp_path / "q.db")}})
    q = JobQueue(cfg, db, llm_factory=lambda c: MockLLM({}), autostart=False)
    pdf = make(tmp_path / "p.pdf")
    a = q.submit(pdf, "cardiology", "plan:api:edit")
    b = q.submit(pdf, "cardiology", "plan:local:termbase", mode=plans.mode_for("plan:local:termbase"))
    q.run_pending()
    assert q.get(a)["status"] == "done" and q.get(b)["status"] == "awaiting_termbase"
    tr = Translator(apply_profile(cfg, "plan:api:draft"), db=db, llm=MockLLM({}))
    tr.run(pdf, out_dir=tmp_path)
    assert tr.is_draft and all(u.status in ("draft", "tm") for u in tr.units if u.kind == "text")
