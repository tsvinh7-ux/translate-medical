"""Lớp gọi Claude API: streaming, suy luận thích ứng, prompt caching, JSON có cấu trúc, tra cứu web,
model dự phòng khi bị từ chối, thống kê chi phí. Có chế độ `mock` để chạy thử không tốn token."""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("medtrans.llm")

# Giá USD / 1 triệu token (input, output, cache_read). Ghi cache 1h = 2x input.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = "web_search_20260209"


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    calls: int = 0
    web_searches: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, u: Any) -> None:
        if u is None:
            return
        with self.lock:
            self.calls += 1
            self.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.output_tokens += getattr(u, "output_tokens", 0) or 0
            self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
            self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
            stu = getattr(u, "server_tool_use", None)
            if stu is not None:
                self.web_searches += getattr(stu, "web_search_requests", 0) or 0

    def cost(self, model: str) -> float:
        pin, pout, pcache = PRICES.get(model, PRICES["claude-opus-5-5"])
        return round((self.input_tokens * pin + self.output_tokens * pout + self.cache_read * pcache
                      + self.cache_write * pin * 2) / 1e6 + self.web_searches * 0.01, 4)

    def as_dict(self, model: str) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read, "cache_write_tokens": self.cache_write,
                "web_searches": self.web_searches, "estimated_cost_usd": self.cost(model)}


def extract_json(text: str) -> Any:
    """Lấy JSON từ văn bản (chịu được ```json ... ``` hoặc <json>...</json>)."""
    m = re.search(r"<json>(.*?)</json>", text, re.S) or re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = min([i for i in (candidate.find("{"), candidate.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        return json.loads(candidate[start:end + 1])


def cached_system(*texts: str) -> list[dict]:
    """System prompt dạng khối; khối cuối được đánh dấu cache 1 giờ (phần ổn định của cả tài liệu)."""
    blocks = [{"type": "text", "text": t} for t in texts if t]
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return blocks


class ClaudeLLM:
    def __init__(self, cfg: dict):
        import anthropic
        self.anthropic = anthropic
        self.cfg = cfg
        self.model = cfg.get("model", "claude-opus-5-5")
        self.client = anthropic.Anthropic(max_retries=cfg.get("max_retries", 4),
                                          timeout=cfg.get("timeout_seconds", 900))
        self.usage = Usage()
        self.use_fallbacks = cfg.get("use_fallbacks", True)

    # ------------------------------------------------------------------ core
    def _stream(self, **kwargs) -> Any:
        params = dict(model=self.model, max_tokens=self.cfg.get("max_tokens", 64000),
                      thinking={"type": "adaptive"}, **kwargs)
        if self.use_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        for attempt in range(3):
            try:
                with self.client.beta.messages.stream(**params) as stream:
                    msg = stream.get_final_message()
                self.usage.add(msg.usage)
                return msg
            except self.anthropic.BadRequestError as e:
                # Nếu tài khoản chưa hỗ trợ model dự phòng → tắt và thử lại
                if self.use_fallbacks and "fallback" in str(e).lower():
                    log.warning("Tắt chế độ model dự phòng: %s", e)
                    self.use_fallbacks = False
                    params.pop("betas", None)
                    params.pop("fallbacks", None)
                    continue
                raise
            except (self.anthropic.APIConnectionError, self.anthropic.InternalServerError) as e:
                wait = 5 * (attempt + 1)
                log.warning("Lỗi kết nối (%s), thử lại sau %ss", e, wait)
                time.sleep(wait)
        raise LLMError("Không gọi được API sau nhiều lần thử")

    @staticmethod
    def _text(msg: Any) -> str:
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def json_call(self, *, task: str, system: list[dict], user: str | list, schema: dict,
                  effort: str = "high", payload: Any = None) -> dict:
        content = user if isinstance(user, list) else [{"type": "text", "text": user}]
        for attempt in range(2):
            msg = self._stream(system=system, messages=[{"role": "user", "content": content}],
                               output_config={"effort": effort,
                                              "format": {"type": "json_schema", "schema": schema}})
            if msg.stop_reason == "refusal":
                details = getattr(msg, "stop_details", None)
                raise LLMError(f"[{task}] Model từ chối: {getattr(details, 'category', '')} "
                               f"{getattr(details, 'explanation', '')}")
            if msg.stop_reason == "max_tokens":
                raise LLMError(f"[{task}] Vượt max_tokens – hãy giảm translation.batch_chars")
            try:
                return extract_json(self._text(msg))
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("[%s] JSON lỗi (%s), thử lại", task, e)
        raise LLMError(f"[{task}] Không đọc được JSON trả về")

    def research_call(self, *, system: list[dict], user: str, max_uses: int = 5, effort: str = "high",
                      payload: Any = None) -> str:
        tools = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}]
        messages: list[dict] = [{"role": "user", "content": user}]
        for _ in range(5):
            msg = self._stream(system=system, messages=messages, tools=tools, output_config={"effort": effort})
            if msg.stop_reason == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": msg.content}]
                continue
            if msg.stop_reason == "refusal":
                raise LLMError("[research] Model từ chối")
            return self._text(msg)
        raise LLMError("[research] Tra cứu không hoàn tất")

    def vision_json_call(self, *, task: str, system: list[dict], image_png: bytes, prompt: str, schema: dict,
                         effort: str = "high", payload: Any = None) -> dict:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(image_png).decode()}},
            {"type": "text", "text": prompt},
        ]
        return self.json_call(task=task, system=system, user=content, schema=schema, effort=effort)


class MockLLM:
    """Giả lập để kiểm thử luồng xử lý mà không gọi API (bản dịch giả có tiền tố [VI])."""

    def __init__(self, cfg: dict):
        self.model = cfg.get("model", "mock")
        self.usage = Usage()

    def json_call(self, *, task: str, system, user, schema, effort="high", payload=None) -> dict:
        self.usage.calls += 1
        p = payload or {}
        if task == "brief":
            return {"title": "Tài liệu thử", "specialty": "general_medicine", "audience": "bác sĩ",
                    "summary": "Mock", "style_guide": "Văn phong học thuật.", "key_terms": []}
        if task in ("translate", "refine"):
            return {"segments": [{"id": s["id"], "translation": _mock_vi(s["text"]), "uncertain_terms": []}
                                 for s in p.get("segments", [])]}
        if task == "review":
            return {"segments": [{"id": s["id"], "score": 90, "final": s["translation"], "problems": []}
                                 for s in p.get("segments", [])]}
        if task == "evaluate":
            return {"segments": [{"id": s["id"], "errors": [], "corrected": ""} for s in p.get("segments", [])]}
        if task == "extract_terms":
            return {"terms": []}
        if task == "validate_terms":
            return {"terms": [{"en": t["en"], "vi": t["vi"], "verdict": "standard", "corrected_vi": "",
                               "confidence": 0.95, "note": "mock"} for t in p.get("terms", [])]}
        if task == "ocr_fix":
            return {"paragraphs": p.get("paragraphs", [])}
        if task == "image_ocr":
            return {"lines": []}
        return {}

    def research_call(self, *, system, user, max_uses=5, effort="high", payload=None) -> str:
        self.usage.calls += 1
        return '<json>{"terms": []}</json>'

    def vision_json_call(self, *, task, system, image_png, prompt, schema, effort="high", payload=None) -> dict:
        return self.json_call(task=task, system=system, user=prompt, schema=schema, payload=payload)


def _mock_vi(text: str) -> str:
    repl = {"patients": "bệnh nhân", "patient": "bệnh nhân", "the": "", "of": "của", "and": "và",
            "with": "với", "is": "là", "are": "là", "for": "cho", "not": "không", "should": "nên",
            "be": "được", "in": "trong", "treatment": "điều trị", "dose": "liều"}
    out = re.sub(r"\b[A-Za-z]+\b", lambda m: repl.get(m.group(0).lower(), m.group(0)), text)
    out = re.sub(r"(\d)\.(\d)", r"\1,\2", out)
    return "[VI] " + re.sub(r"\s{2,}", " ", out).strip()


def make_llm(cfg: dict):
    provider = cfg.get("provider", "anthropic")
    if provider == "mock":
        return MockLLM(cfg)
    return ClaudeLLM(cfg)
