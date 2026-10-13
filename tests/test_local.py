"""Kiểm thử đường ống chạy LOCAL (giao thức OpenAI-compatible, MedCrab, định tuyến) bằng máy chủ HTTP giả lập.

Đây là kiểm thử KẾT NỐI & XỬ LÝ (prompt đúng định dạng, chia đoạn, mã giữ chỗ, JSON, định tuyến),
KHÔNG phải đánh giá chất lượng model – chất lượng phải đo bằng chức năng Hiệu chuẩn trên máy có GPU.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample import make  # noqa: E402

from medtrans.config import apply_profile, load_config  # noqa: E402
from medtrans.llm import MockLLM, make_llm  # noqa: E402
from medtrans.llm_local import MedCrabLLM, OpenAICompatLLM, RoutedLLM  # noqa: E402
from medtrans.translator import Translator  # noqa: E402

SEEN: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"path": self.path, "body": body})
        if self.path.endswith("/completions") and "prompt" in body:      # MedCrab
            m = re.search(r"<\|ENGLISH_TEXT_START\|>(.*)<\|ENGLISH_TEXT_END\|>", body["prompt"], re.S)
            text = m.group(1)
            self._send({"choices": [{"text": f"VI[{len(text.split())}w] {text}<|VIETNAMESE_TEXT_END|>"}],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 40}})
            return
        user = body["messages"][-1]["content"]                            # chat completions
        payload = json.loads(user[user.index("{"):]) if isinstance(user, str) and "{" in user else {}
        segs = [{"id": s["id"], "translation": "Bản dịch local", "uncertain_terms": []}
                for s in payload.get("segments", [])]
        self._send({"choices": [{"message": {"content": "<think>suy nghĩ</think>" + json.dumps({"segments": segs})}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_openai_compatible_json_schema(server):
    SEEN.clear()
    llm = OpenAICompatLLM({"base_url": server, "model": "qwen3:32b"})
    from medtrans import prompts as P
    res = llm.json_call(task="translate", system=[{"type": "text", "text": "SYS"}],
                        user="Dịch:\n" + json.dumps({"segments": [{"id": "a", "text": "Heart failure."}]}),
                        schema=P.TRANSLATE_SCHEMA)
    assert res["segments"][0]["translation"] == "Bản dịch local"      # bỏ được khối <think> của Qwen3
    body = SEEN[-1]["body"]
    assert body["model"] == "qwen3:32b" and body["response_format"]["type"] == "json_schema"
    assert llm.usage.output_tokens == 20 and llm.usage.cost("qwen3:32b") == 0.0   # local: không tốn phí API


def test_medcrab_prompt_chunking_and_markers(server):
    SEEN.clear()
    mc = MedCrabLLM({"base_url": server})
    long = " ".join(f"Sentence number {i} describes heart failure in detail." for i in range(40))  # ~280 từ
    out = mc.json_call(task="translate", system=None, user="", schema={},
                       payload={"segments": [{"id": "s1", "text": f"<b>Intro</b> text. ⟦¶⟧ {long}"}]})
    vi = out["segments"][0]["translation"]
    assert vi.count("⟦¶⟧") == 1                                     # giữ ranh giới khối
    prompts = [s["body"]["prompt"] for s in SEEN]
    assert all(p.startswith("<|user|>: Translate the following medical text") for p in prompts)
    assert all(len(re.search(r"START\|>(.*)<\|ENGLISH", p, re.S).group(1).split()) <= 150 for p in prompts)
    assert len(prompts) >= 3 and "<b>" not in "".join(prompts)       # chia ≤150 từ, bỏ thẻ định dạng
    with pytest.raises(Exception):
        mc.json_call(task="evaluate", system=None, user="", schema={}, payload={})


def test_routes_from_config(server):
    cfg = load_config()
    llm_cfg = dict(cfg["llm"], provider="local", routes={"translate": "medcrab"},
                   local={"base_url": server}, medcrab={"base_url": server})
    r = make_llm(llm_cfg)
    assert isinstance(r, RoutedLLM)
    assert isinstance(r._pick("translate"), MedCrabLLM) and isinstance(r._pick("evaluate"), OpenAICompatLLM)


def test_hybrid_pipeline_translate_local_rest_api(server, tmp_path):
    """Lai: bước dịch qua MedCrab (local), mọi bước kiểm định qua backend chính (ở đây giả lập)."""
    SEEN.clear()
    cfg = apply_profile(load_config(overrides={"memory": {"db_path": str(tmp_path / "h.db")}}), "hybrid")
    routed = RoutedLLM({"mock": MockLLM({}), "medcrab": MedCrabLLM({"base_url": server})},
                       {"translate": "medcrab"}, "mock")
    res = Translator(cfg, llm=routed).run(make(tmp_path / "h.pdf"), out_dir=tmp_path)
    assert Path(res["output_pdf"]).exists()
    assert any(s["path"].endswith("/completions") for s in SEEN)      # bước dịch đã đi qua MedCrab
    assert res["usage"]["estimated_cost_usd"] == 0.0


def test_local_fast_profile_is_draft(server, tmp_path):
    cfg = apply_profile(load_config(overrides={"memory": {"db_path": str(tmp_path / "f.db")}}), "local_fast")
    cfg["llm"]["medcrab"]["base_url"] = server
    tr = Translator(cfg)
    res = tr.run(make(tmp_path / "f.pdf"), out_dir=tmp_path)
    assert Path(res["output_pdf"]).exists() and tr.is_draft
    assert all(u.status == "draft" for u in tr.units if u.kind == "text")


def test_finetune_export_defaults_to_human_data(tmp_path):
    from medtrans.db import Database
    from medtrans.finetune import export_jsonl
    from medtrans.glossary import import_file
    db = Database(tmp_path / "ft.db")
    import_file(db, Path(__file__).resolve().parent.parent / "data" / "glossary_seed.csv")
    db.tm_add("Heart failure is common.", "Suy tim là bệnh thường gặp.", "cardiology", quality=100, approved=True,
              origin="human")
    db.tm_add("Stroke is an emergency.", "Đột quỵ là cấp cứu.", "cardiology", quality=98, approved=True)
    res = export_jsonl(db, tmp_path / "ft")
    assert res["train"] + res["val"] == 1 and res["by_origin"] == {"human": 1}
    line = json.loads((tmp_path / "ft" / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "heart failure → suy tim" in line["messages"][1]["content"]   # kèm thuật ngữ bắt buộc
    res2 = export_jsonl(db, tmp_path / "ft2", include_machine=True)
    assert res2["by_origin"].get("machine") == 1


# ---------------------------------------------------------------- leo thang có điều kiện (local → API)
class WeakLocal(MockLLM):
    """Giám khảo local báo lỗi major cho đoạn chứa 'Beta-blockers' → phải leo thang."""

    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        if task == "evaluate":
            return {"segments": [{"id": s["id"], "corrected": "", "errors": (
                [{"category": "terminology", "severity": "major", "source_span": "", "target_span": "",
                  "explanation": "nghi sai", "fix": ""}] if "Beta-blockers" in s["source"] else [])}
                for s in payload["segments"]]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


class StrongAPI(MockLLM):
    def __init__(self):
        super().__init__({})
        self.tasks: list[str] = []

    def json_call(self, *, task, system, user, schema, effort="high", payload=None):
        self.tasks.append(task)
        if task == "refine":
            return {"segments": [{"id": s["id"], "translation": "Không khuyến cáo dùng thuốc chẹn beta ở bệnh nhân.",
                                  "uncertain_terms": []} for s in payload["segments"]]}
        return super().json_call(task=task, system=system, user=user, schema=schema, effort=effort, payload=payload)


def test_cascade_escalates_only_failing_segments(tmp_path):
    cfg = apply_profile(load_config(overrides={"memory": {"db_path": str(tmp_path / "c.db")}}), "local_cascade")
    cfg["escalation"]["audit_rate"] = 0.0
    api = StrongAPI()
    tr = Translator(cfg, llm=WeakLocal({}), escalation_llm=api)
    res = tr.run(make(tmp_path / "c.pdf"), out_dir=tmp_path)
    esc = res["escalation"]
    assert esc["escalated"] >= 1 and esc["escalated"] < res["segments"]     # chỉ một phần đoạn phải gọi API
    assert "refine" in api.tasks and "evaluate" in api.tasks
    beta = next(u for u in tr.units if "Beta-blockers" in u.plain_src)
    assert beta.verified and beta.tgt.startswith("Không khuyến cáo")
    # đoạn chỉ qua cổng local (chưa API xác nhận) không được chứng nhận vào bộ nhớ dịch đạt chuẩn
    assert all(u.status != "certified" for u in tr.units if u.kind == "text" and not u.verified)


def test_cascade_audit_sampling_measures_local_judge(tmp_path):
    cfg = apply_profile(load_config(overrides={"memory": {"db_path": str(tmp_path / "a.db")}}), "local_cascade")
    cfg["escalation"]["audit_rate"] = 1.0                                     # kiểm tra mẫu toàn bộ
    tr = Translator(cfg, llm=MockLLM({}), escalation_llm=StrongAPI())
    res = tr.run(make(tmp_path / "a.pdf"), out_dir=tmp_path)
    assert res["escalation"]["audited"] >= 1
    assert res["escalation"]["local_judge_agreement_percent"] is not None


def test_hardware_tiers():
    from medtrans.hardware import recommend
    r = recommend({"gpus": [{"name": "NVIDIA GeForce RTX 3050", "vram_gb": 8.0}], "ram_gb": 16})
    assert "qwen3:8b" in r["local_model"] and r["profile"].startswith("local_cascade")
    r4 = recommend({"gpus": [{"name": "RTX 3050 Laptop", "vram_gb": 4.0}], "ram_gb": 16})
    assert "4b" in r4["local_model"]
    assert "12–16 GB" in r["upgrade"]
    r24 = recommend({"gpus": [{"name": "RTX 3090", "vram_gb": 24.0}], "ram_gb": 32})
    assert r24["profile"].startswith("local_pro") and "64 GB" in r24["note"]


def test_local_pro_cross_family_judge(server):
    """Local Pro: model dịch và model giám khảo là HAI backend local khác nhau; Claude chỉ tra web/đọc morat."""
    cfg = apply_profile(load_config(), "local_pro")
    llm_cfg = dict(cfg["llm"], local=dict(cfg["llm"]["local"], base_url=server),
                   local_judge=dict(cfg["llm"]["local_judge"], base_url=server),
                   routes={k: v for k, v in cfg["llm"]["routes"].items() if v != "anthropic"})
    r = make_llm(llm_cfg)
    assert isinstance(r, RoutedLLM)
    tr, judge = r._pick("translate"), r._pick("evaluate")
    assert tr is not judge and r._pick("fidelity") is judge
    assert tr.model != judge.model                                       # khác model → không tự chấm bài mình
    assert cfg["escalation"]["enabled"] and cfg["llm"]["routes"]["research"] == "anthropic"
