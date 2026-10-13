"""Chạy model LOCAL (không cần Internet / API trả phí) và định tuyến từng công đoạn tới model phù hợp.

Hỗ trợ:
  • OpenAICompatLLM – mọi máy chủ model local có API chuẩn OpenAI: Ollama, llama.cpp server, vLLM, LM Studio,
    SGLang, TGI. Dùng cho dịch / hiệu đính / biên tập / giám khảo với model đủ mạnh (Qwen3-32B, Qwen2.5-72B...).
    JSON có cấu trúc qua response_format=json_schema (vLLM, llama.cpp, LM Studio) hoặc format (Ollama).
  • MedCrabLLM – model dịch chuyên dụng pnnbao-ump/MedCrab-1.5B (Qwen2.5-1.5B tinh chỉnh Anh→Việt y khoa).
    Chỉ làm được bước DỊCH (không theo được chỉ dẫn/JSON) → dùng làm "máy dịch nháp" nhanh, các bước kiểm soát
    chất lượng do model khác đảm nhiệm. LƯU Ý GIẤY PHÉP: CC BY-NC 4.0 – dùng thương mại phải xin phép tác giả.
  • RoutedLLM – định tuyến theo công đoạn, ví dụ: translate → medcrab, còn lại → local Qwen hoặc Claude API.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from typing import Any

import os

from .llm import LLMError, PricedUsage, Usage, extract_json

log = logging.getLogger("medtrans.local")
TAGS = re.compile(r"</?(?:b|i|sup|sub)>")
PH = re.compile(r"⟦\w+⟧")


def _flatten_system(system: list[dict] | str | None) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))


def _http():
    import httpx2
    return httpx2


class OpenAICompatLLM:
    """Model local qua API chuẩn OpenAI (chat completions)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base_url = cfg.get("base_url", "http://localhost:11434/v1").rstrip("/")
        self.model = cfg.get("model", "qwen3:32b")
        self.vision_model = cfg.get("vision_model") or (self.model if cfg.get("vision") else None)
        self.name = cfg.get("name", "local")
        self.api_key = cfg.get("api_key") or os.environ.get(cfg.get("api_key_env") or "", "") or "local"
        self.trust_env = bool(cfg.get("trust_env", False))   # máy chủ local: không qua proxy; nhà cung cấp cloud: có
        self.json_mode = cfg.get("json_mode", "json_schema")   # json_schema | json_object | ollama | none
        self.temperature = float(cfg.get("temperature", 0.1))
        self.max_tokens = int(cfg.get("max_tokens", 16000))
        self.timeout = float(cfg.get("timeout_seconds", 1800))
        self.retries = int(cfg.get("max_retries", 3))
        self.extra = cfg.get("extra_body") or {}
        price = cfg.get("price_per_mtok")
        self.usage = PricedUsage(price_in=float(price[0]), price_out=float(price[1])) if price else Usage()
        self._client = None
        self._lock = threading.Lock()

    @property
    def client(self):
        with self._lock:
            if self._client is None:
                httpx = _http()
                # máy chủ local: không đi qua proxy hệ thống
                self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout, trust_env=self.trust_env,
                                            headers={"Authorization": f"Bearer {self.api_key}"})
            return self._client

    def _chat(self, messages: list[dict], schema: dict | None, model: str | None = None) -> str:
        body: dict[str, Any] = {"model": model or self.model, "messages": messages, "temperature": self.temperature,
                                "max_tokens": self.max_tokens, "stream": False, **self.extra}
        if schema is not None:
            if self.json_mode == "json_schema":
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "result", "schema": schema, "strict": True}}
            elif self.json_mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            elif self.json_mode == "ollama":
                body["format"] = schema
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = self.client.post("/chat/completions", json=body)
                if r.status_code >= 500 or r.status_code == 429:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code >= 400:
                    raise LLMError(f"Máy chủ model '{self.name}' từ chối ({r.status_code}): {r.text[:500]}")
                data = r.json()
                u = data.get("usage") or {}
                with self.usage.lock:
                    self.usage.calls += 1
                    self.usage.input_tokens += int(u.get("prompt_tokens") or 0)
                    self.usage.output_tokens += int(u.get("completion_tokens") or 0)
                msg = data["choices"][0]["message"]
                return msg.get("content") or ""
            except LLMError as e:
                last = e
                if "từ chối" in str(e):
                    raise
            except Exception as e:  # noqa: BLE001 – lỗi kết nối
                last = LLMError(f"Không kết nối được máy chủ model '{self.name}' {self.base_url}: {e}")
            time.sleep(min(30, 3 * (attempt + 1)))
        raise last or LLMError("Lỗi model local")

    def json_call(self, *, task: str, system, user, schema: dict, effort: str = "high", payload: Any = None) -> dict:
        sys_txt = _flatten_system(system) + (
            "\n\nTRẢ LỜI DUY NHẤT BẰNG MỘT ĐỐI TƯỢNG JSON hợp lệ theo đúng lược đồ sau (không giải thích, không markdown):\n"
            + json.dumps(schema, ensure_ascii=False))
        content = user if isinstance(user, str) else self._content_parts(user)
        model = self.vision_model if not isinstance(user, str) and self._has_image(user) else None
        if not isinstance(user, str) and self._has_image(user) and not self.vision_model:
            raise LLMError(f"[{task}] Model local không hỗ trợ hình ảnh – cấu hình llm.local.vision_model")
        for attempt in range(2):
            text = self._chat([{"role": "system", "content": sys_txt}, {"role": "user", "content": content}],
                              schema, model=model)
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # model suy luận (Qwen3) có thể trả khối think
            try:
                return extract_json(text)
            except (json.JSONDecodeError, ValueError):
                log.warning("[%s] JSON local lỗi, thử lại", task)
        raise LLMError(f"[{task}] Model local không trả JSON hợp lệ")

    @staticmethod
    def _has_image(parts) -> bool:
        return any(isinstance(p, dict) and p.get("type") == "image" for p in parts)

    @staticmethod
    def _content_parts(parts: list) -> list:
        out = []
        for p in parts:
            if p.get("type") == "image":
                src = p["source"]
                out.append({"type": "image_url",
                            "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
            elif p.get("type") == "text":
                out.append({"type": "text", "text": p["text"]})
        return out

    def research_call(self, *, system, user, max_uses=5, effort="high", payload=None) -> str:
        raise LLMError("Chạy local không có tra cứu web – thuật ngữ chưa chắc được giữ phương án tốt nhất "
                       "(nên khoá termbase trước khi dịch)")

    def vision_json_call(self, *, task, system, image_png: bytes, prompt: str, schema: dict, effort="high",
                         payload=None) -> dict:
        return self.vision_multi_json_call(task=task, system=system, images=[image_png], prompt=prompt,
                                           schema=schema, effort=effort, payload=payload)

    def vision_multi_json_call(self, *, task, system, images: list[bytes], prompt: str, schema: dict,
                               effort="high", payload=None) -> dict:
        parts = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": base64.standard_b64encode(im).decode()}} for im in images]
        parts.append({"type": "text", "text": prompt})
        return self.json_call(task=task, system=system, user=parts, schema=schema, effort=effort, payload=payload)


class MedCrabLLM:
    """MedCrab-1.5B: chỉ làm bước dịch (prompt cố định của tác giả). Engine:
       - "completions": gọi /v1/completions của vLLM / llama.cpp đang phục vụ MedCrab (khuyến nghị, nhanh);
       - "transformers": nạp model trực tiếp bằng transformers + torch (cần GPU ≥ 4 GB hoặc CPU rất chậm)."""

    PROMPT = ("<|user|>: Translate the following medical text from English to Vietnamese:"
              "<|ENGLISH_TEXT_START|>{text}<|ENGLISH_TEXT_END|>\n<|assistant|>:<|VIETNAMESE_TEXT_START|>")
    STOP = "<|VIETNAMESE_TEXT_END|>"
    MAX_WORDS = 150   # tác giả khuyến nghị đoạn 100–150 từ

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg.get("model", "pnnbao-ump/MedCrab-1.5B")
        self.engine = cfg.get("engine", "completions")
        self.base_url = cfg.get("base_url", "http://localhost:8001/v1").rstrip("/")
        self.max_new_tokens = int(cfg.get("max_new_tokens", 1024))
        self.usage = Usage()
        self._hf = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ engines
    def _gen_completions(self, prompt: str) -> str:
        httpx = _http()
        r = httpx.post(f"{self.base_url}/completions", timeout=600, trust_env=False,
                       json={"model": self.model, "prompt": prompt, "max_tokens": self.max_new_tokens,
                             "temperature": 0, "stop": [self.STOP]})
        if r.status_code >= 400:
            raise LLMError(f"MedCrab server lỗi {r.status_code}: {r.text[:300]}")
        data = r.json()
        u = data.get("usage") or {}
        with self.usage.lock:
            self.usage.calls += 1
            self.usage.input_tokens += int(u.get("prompt_tokens") or 0)
            self.usage.output_tokens += int(u.get("completion_tokens") or 0)
        return data["choices"][0].get("text", "")

    def _gen_transformers(self, prompt: str) -> str:
        with self._lock:
            if self._hf is None:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                dev = "cuda" if torch.cuda.is_available() else "cpu"
                tok = AutoTokenizer.from_pretrained(self.model, trust_remote_code=True)
                mdl = AutoModelForCausalLM.from_pretrained(
                    self.model, torch_dtype=torch.bfloat16 if dev == "cuda" else torch.float32).to(dev).eval()
                self._hf = (tok, mdl, dev)
            tok, mdl, dev = self._hf
            import torch
            inputs = tok(prompt, return_tensors="pt").to(dev)
            eos = tok.get_vocab().get(self.STOP, tok.eos_token_id)
            with torch.no_grad():
                out = mdl.generate(**inputs, max_new_tokens=self.max_new_tokens, eos_token_id=eos, do_sample=False)
            self.usage.calls += 1
            return tok.decode(out[0, inputs["input_ids"].shape[-1]:], skip_special_tokens=True)

    def translate_text(self, text: str) -> str:
        """Dịch 1 đoạn: chia ≤150 từ theo câu, giữ URL/công thức bằng cách thay mã giữ chỗ bằng nội dung gốc."""
        from .fidelity import split_sentences
        parts, cur, n = [], [], 0
        for s in split_sentences(text) or [text]:
            w = len(s.split())
            if cur and n + w > self.MAX_WORDS:
                parts.append(" ".join(cur))
                cur, n = [], 0
            cur.append(s)
            n += w
        if cur:
            parts.append(" ".join(cur))
        gen = self._gen_completions if self.engine == "completions" else self._gen_transformers
        outs = []
        for p in parts:
            out = gen(self.PROMPT.format(text=p)).split(self.STOP)[0].strip()
            outs.append(out)
        return " ".join(outs)

    # ------------------------------------------------------------ giao diện chung
    def json_call(self, *, task: str, system, user, schema: dict, effort: str = "high", payload: Any = None) -> dict:
        if task not in ("translate",) or not payload or "segments" not in payload:
            raise LLMError(f"MedCrab chỉ làm được bước dịch, không làm được '{task}' – định tuyến bước này "
                           "cho model khác (llm.routes)")
        segs = []
        for s in payload["segments"]:
            text = s["text"]
            # MedCrab không được huấn luyện với thẻ định dạng / mã giữ chỗ → bỏ thẻ; mã giữ chỗ giữ nguyên dạng ⟦n⟧
            # (các bước sau – kiểm tra máy, hiệu đính, giám khảo – phát hiện & sửa nếu mất)
            plain = TAGS.sub("", text)
            pieces = re.split(r"\s*⟦¶⟧\s*", plain)
            vi = " ⟦¶⟧ ".join(self.translate_text(p) if p.strip() else p for p in pieces)
            segs.append({"id": s["id"], "translation": vi, "uncertain_terms": []})
        return {"segments": segs}

    def research_call(self, **_) -> str:
        raise LLMError("MedCrab không tra cứu web")

    def vision_json_call(self, **kw) -> dict:
        raise LLMError("MedCrab không đọc hình ảnh")

    def vision_multi_json_call(self, **kw) -> dict:
        raise LLMError("MedCrab không đọc hình ảnh")


class RoutedLLM:
    """Định tuyến theo công đoạn: routes = {"translate": "medcrab", "evaluate": "anthropic", ...}."""

    def __init__(self, backends: dict[str, Any], routes: dict[str, str], primary: str):
        self.backends = backends
        self.routes = routes or {}
        self.primary = primary
        self.model = getattr(backends[primary], "model", primary)

    def _pick(self, task: str):
        return self.backends[self.routes.get(task, self.primary)]

    @property
    def usage(self) -> "Usage":
        return _RoutedUsage(list(self.backends.values()))

    def json_call(self, *, task: str, **kw) -> dict:
        return self._pick(task).json_call(task=task, **kw)

    def research_call(self, **kw) -> str:
        return self._pick("research").research_call(**kw)

    def vision_json_call(self, *, task: str, **kw) -> dict:
        return self._pick(task).vision_json_call(task=task, **kw)

    def vision_multi_json_call(self, *, task: str, **kw) -> dict:
        return self._pick(task).vision_multi_json_call(task=task, **kw)


class _RoutedUsage(Usage):
    """Gộp thống kê token của các backend; chi phí chỉ tính phần gọi API trả phí."""

    def __init__(self, backends: list):
        super().__init__()
        self._backends = backends
        for b in backends:
            u = b.usage
            self.calls += u.calls
            self.input_tokens += u.input_tokens
            self.output_tokens += u.output_tokens
            self.cache_read += u.cache_read
            self.cache_write += u.cache_write
            self.web_searches += u.web_searches

    def cost(self, model: str) -> float:
        return round(sum(b.usage.cost(getattr(b, "model", "")) for b in self._backends), 4)


class FailoverLLM:
    """DỰ PHÒNG nhiều nhà cung cấp: gọi lần lượt theo thứ tự ưu tiên; nhà cung cấp lỗi / quá tải / bị từ chối →
    chuyển sang nhà cung cấp kế tiếp cho LẦN GỌI ĐÓ (lần sau vẫn thử lại nhà cung cấp chính).
    Mọi kết quả, dù từ nhà cung cấp nào, vẫn đi qua CÙNG cổng kiểm tra máy + giám khảo + kiểm toán trung thành."""

    def __init__(self, chain: list[Any]):
        self.chain = chain
        self.model = getattr(chain[0], "model", "")
        self.events: list[dict] = []
        self._lock = threading.Lock()

    @property
    def usage(self) -> Usage:
        return _RoutedUsage(self.chain)

    def _run(self, method: str, kw: dict):
        last = None
        for i, b in enumerate(self.chain):
            try:
                out = getattr(b, method)(**kw)
                if i:
                    with self._lock:
                        self.events.append({"task": kw.get("task", method), "used": getattr(b, "model", str(i)),
                                            "error": str(last)[:200]})
                return out
            except Exception as e:  # noqa: BLE001 – lỗi nhà cung cấp: thử nhà cung cấp kế tiếp
                last = e
                log.warning("Nhà cung cấp %s lỗi ở %s (%s) → chuyển dự phòng", getattr(b, "model", i),
                            kw.get("task", method), str(e)[:160])
        raise LLMError(f"Mọi nhà cung cấp đều lỗi: {last}")

    def json_call(self, **kw) -> dict:
        return self._run("json_call", kw)

    def research_call(self, **kw) -> str:
        return self._run("research_call", kw)

    def vision_json_call(self, **kw) -> dict:
        return self._run("vision_json_call", kw)

    def vision_multi_json_call(self, **kw) -> dict:
        return self._run("vision_multi_json_call", kw)
