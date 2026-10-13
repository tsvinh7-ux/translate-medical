"""Tư vấn phần cứng & đo tốc độ model local THẬT trên máy người dùng."""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time

# (VRAM tối thiểu GB, khuyến nghị) – model lượng tử 4-bit qua Ollama/llama.cpp
TIERS = [
    (0, {"tier": "Không có GPU NVIDIA", "local_model": "qwen3:4b (chạy CPU, rất chậm)", "profile": "premium / economy",
         "note": "Nên dùng API cho bước dịch; máy vẫn làm tốt OCR, phân tích, dàn trang, hàng đợi."}),
    (3.5, {"tier": "GPU 4–6 GB (vd RTX 3050 laptop 4 GB)", "local_model": "qwen3:4b hoặc MedCrab-1.5B",
           "profile": "local_cascade (model qwen3:4b) hoặc hybrid",
           "note": "Đủ cho dịch nháp; giám khảo local yếu → tỉ lệ leo thang lên API cao (ước 40–60%)."}),
    (7.5, {"tier": "GPU 8 GB (vd RTX 3050 8 GB, 3060 Ti, 4060)", "local_model": "qwen3:8b (Q4_K_M ≈ 5,5 GB)",
           "profile": "local_cascade",
           "note": "Dịch + tự chấm cơ bản trên máy; đoạn khó leo thang API (ước 25–40%). Không chạy được 14B+ đủ nhanh."}),
    (11.5, {"tier": "GPU 12–16 GB (RTX 3060 12 GB, 4060 Ti 16 GB, 4080)", "local_model": "qwen3:14b (Q4 ≈ 9 GB)",
            "profile": "local_cascade (model qwen3:14b)", "note": "Chất lượng local khá; leo thang ước 15–30%."}),
    (23, {"tier": "GPU 24 GB (RTX 3090/4090)", "local_model": "qwen3:32b (Q4 ≈ 20 GB)",
          "profile": "local_cascade (qwen3:32b) hoặc local_quality",
          "note": "Có thể chạy toàn quy trình local; vẫn nên kiểm tra mẫu bằng API."}),
    (47, {"tier": "GPU ≥ 48 GB / nhiều GPU (A6000, A100, H100)", "local_model": "Qwen 32B–72B qua vLLM",
          "profile": "local_quality / local_cascade", "note": "Thông lượng cao (vLLM xử lý theo lô)."}),
]


def detect() -> dict:
    gpus = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in out.strip().splitlines():
                name, mem = [x.strip() for x in line.split(",")]
                gpus.append({"name": name, "vram_gb": round(float(mem) / 1024, 1)})
        except Exception:  # noqa: BLE001
            pass
    return {"os": platform.platform(), "cpu": platform.processor() or platform.machine(), "ram_gb": _ram_gb(),
            "gpus": gpus}


def _ram_gb() -> float | None:
    try:
        if platform.system() == "Windows":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong * 6)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 2 ** 30, 1)
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout
            return round(int(out) / 2 ** 30, 1)
        txt = open("/proc/meminfo").read()
        return round(int(re.search(r"MemTotal:\s+(\d+)", txt).group(1)) / 2 ** 20, 1)
    except Exception:  # noqa: BLE001
        return None


def recommend(info: dict) -> dict:
    vram = max((g["vram_gb"] for g in info.get("gpus", [])), default=0)
    rec = TIERS[0][1]
    for need, r in TIERS:
        if vram >= need:
            rec = r
    out = {**rec, "vram_gb": vram}
    if info.get("ram_gb") and info["ram_gb"] < 16:
        out["note"] += " RAM < 16 GB: nên nâng lên 16–32 GB để chạy model + PDF lớn ổn định."
    return out


BENCH_TEXT = ("Heart failure with reduced ejection fraction is defined as a left ventricular ejection fraction of 40% "
              "or less. Guideline-directed medical therapy includes an angiotensin receptor–neprilysin inhibitor, a "
              "beta-blocker, a mineralocorticoid receptor antagonist and an SGLT2 inhibitor, which together reduce "
              "mortality and hospitalization. Beta-blockers are not recommended in patients with acute "
              "decompensated heart failure and hypotension (systolic blood pressure < 90 mmHg).")


def bench(cfg) -> dict:
    """Đo thông lượng thật của model local đang chạy + kiểm tra khả năng trả JSON."""
    from .llm_local import OpenAICompatLLM
    from . import prompts as P
    lcfg = dict(cfg.get_path("llm.local", {}) or {})
    llm = OpenAICompatLLM(lcfg)
    t0 = time.time()
    res = llm.json_call(task="translate", system="Bạn là dịch giả y khoa Anh → Việt.",
                        user="Dịch đoạn sau:\n" + json.dumps({"segments": [{"id": "b1", "text": BENCH_TEXT}]},
                                                             ensure_ascii=False),
                        schema=P.TRANSLATE_SCHEMA)
    dt = time.time() - t0
    out_tok = llm.usage.output_tokens or 1
    seg = (res.get("segments") or [{}])[0]
    return {"model": llm.model, "seconds": round(dt, 1), "output_tokens": out_tok,
            "tokens_per_sec": round(out_tok / dt, 1), "json_ok": bool(seg.get("translation")),
            "sample_translation": seg.get("translation", "")[:400]}


def save_throughput(config_path, tps: float) -> None:
    from pathlib import Path
    p = Path(config_path)
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"(  local:[\s\S]*?throughput_tokens_per_sec: )[\d.]+", lambda m: f"{m.group(1)}{tps:.0f}", s, count=1)
    p.write_text(s, encoding="utf-8")
