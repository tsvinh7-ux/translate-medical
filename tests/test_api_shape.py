"""Kiểm tra request gửi Claude API đúng định dạng (dùng máy chủ giả lập, không cần API key)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic
import httpx2 as httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medtrans import prompts as P  # noqa: E402
from medtrans.llm import ClaudeLLM, cached_system, extract_json  # noqa: E402


def _sse(model: str, text: str) -> bytes:
    ev = [("message_start", {"type": "message_start", "message": {
        "id": "m", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None,
        "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 7}}),
        ("message_stop", {"type": "message_stop"})]
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in ev).encode()


def _llm(captured: list) -> ClaudeLLM:
    def handler(req):
        body = json.loads(req.content)
        captured.append((dict(req.headers), body))
        text = ('<json>{"terms": []}</json>' if body.get("tools")
                else json.dumps({"segments": [{"id": "a", "translation": "Suy tim", "uncertain_terms": []}]}))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(body["model"], text))

    llm = ClaudeLLM({"model": "claude-opus-5-5"})
    llm.client = anthropic.Anthropic(api_key="x", base_url="http://stub",
                                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return llm


def test_translate_request_shape():
    captured: list = []
    llm = _llm(captured)
    out = llm.json_call(task="translate", system=cached_system("A", "B"), user="x", schema=P.TRANSLATE_SCHEMA)
    assert out["segments"][0]["translation"] == "Suy tim"
    headers, body = captured[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert llm.usage.calls == 1


def test_research_uses_web_search():
    captured: list = []
    llm = _llm(captured)
    text = llm.research_call(system=cached_system("R"), user="q", max_uses=3)
    assert extract_json(text) == {"terms": []}
    assert captured[0][1]["tools"][0]["type"] == "web_search_20260209"
