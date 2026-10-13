"""GÓI CÔNG VIỆC chuẩn: 2 PHƯƠNG THỨC xử lý × 5 PHẠM VI công việc.

Phương thức (engine):
  • local – AI chạy trên máy (Qwen/Gemma) làm phần lớn; Claude API hỗ trợ tra web, đoạn khó, kiểm tra mẫu, đọc morat.
  • api   – Toàn bộ quy trình bằng Claude API (chất lượng cao nhất, nhanh nhất khi chạy nhiều luồng).

Phạm vi (scope) – mỗi mức bao gồm mức trước:
  termbase → draft (dịch thô) → edit (+ biên tập) → revise (+ hiệu đính) → publish (+ đọc morat).

Tên gói dùng như tên hồ sơ: "plan:<engine>:<scope>[:w<số luồng>]", ví dụ "plan:local:revise", "plan:api:publish:w32"
– áp bằng config.apply_profile.
"""
from __future__ import annotations

import functools

from .config import Config, _deep_merge

ENGINES = {
    "local": {
        "label": "AI Local + API hỗ trợ", "short": "Local + API", "icon": "🖥️",
        "tagline": "Model AI chạy trên máy bạn làm phần lớn công việc – miễn phí, dữ liệu không rời máy",
        "roles": [("Dịch · biên tập · hiệu đính", "Qwen trên GPU của bạn"),
                  ("Giám khảo MQM · kiểm toán trung thành", "Model local (khác họ khi đủ VRAM)"),
                  ("Tra cứu web · đoạn khó · kiểm tra mẫu", "Claude API – chỉ khi cần"),
                  ("Đọc morat bằng hình ảnh", "Claude API")],
        "pros": "Chi phí API thấp nhất · chủ động, không phụ thuộc",
        "cons": "Tốc độ phụ thuộc GPU · cần chạy Ollama/vLLM",
    },
    "api": {
        "label": "API hoàn toàn", "short": "API", "icon": "☁️",
        "tagline": "Toàn bộ quy trình do Claude đảm nhiệm – chất lượng cao nhất, nhanh nhờ chạy song song",
        "roles": [("Dịch · biên tập · hiệu đính", "Claude Opus"),
                  ("Hội đồng MQM 2 giám khảo · kiểm toán", "Claude Opus"),
                  ("Tra cứu web thuật ngữ", "Claude + web search"),
                  ("Đọc morat bằng hình ảnh", "Claude Opus (thị giác)")],
        "pros": "Chất lượng & tốc độ cao nhất · không cần GPU",
        "cons": "Trả phí theo token",
    },
}

# (mã, tên, mô tả, công đoạn hiển thị, sản phẩm bàn giao)
STAGE_KEYS = [("terms", "Thuật ngữ"), ("translate", "Dịch"), ("edit", "Biên tập"), ("revise", "Hiệu đính"),
              ("proof", "Đọc morat")]
SCOPES = [
    {"key": "termbase", "label": "Dịch thuật ngữ", "badge": "Termbase",
     "desc": "Quét toàn văn, trích & dịch thuật ngữ, tra cứu khi chưa chắc → xuất Excel/TBX cho chuyên gia "
             "kiểm tra và khoá trước khi dịch chính thức.",
     "stages": {"terms"}, "deliver": "Termbase Excel + TBX"},
    {"key": "draft", "label": "Dịch thô", "badge": "Bản nháp",
     "desc": "Dịch nhanh toàn văn theo termbase, giữ bố cục PDF. Dùng để đọc hiểu, ước lượng, chia việc – "
             "chưa qua biên tập, không chứng nhận.",
     "stages": {"terms", "translate"}, "deliver": "PDF tiếng Việt (bản thô)"},
    {"key": "edit", "label": "Dịch + Biên tập", "badge": "Chuẩn đọc",
     "desc": "Dịch + biên tập ngôn ngữ (mượt, đúng văn phong), giám khảo ngôn ngữ, kiểm toán dịch đúng – đủ – "
             "đúng trình tự, biên tập thống nhất toàn văn.",
     "stages": {"terms", "translate", "edit"}, "deliver": "PDF tiếng Việt + báo cáo chất lượng"},
    {"key": "revise", "label": "Dịch + Biên tập + Hiệu đính", "badge": "Chuyên môn",
     "desc": "Thêm hiệu đính chuyên môn y khoa đối chiếu bản gốc và hội đồng MQM 2 giám khảo (lâm sàng + ngôn ngữ).",
     "stages": {"terms", "translate", "edit", "revise"}, "deliver": "PDF + báo cáo song ngữ + MQM"},
    {"key": "publish", "label": "Trọn gói xuất bản", "badge": "Xuất bản",
     "desc": "Toàn bộ quy trình + đọc morat trên trang đã dàn (hình ảnh), sửa morat, kiểm tra bố cục – sẵn sàng in.",
     "stages": {"terms", "translate", "edit", "revise", "proof"}, "deliver": "PDF sẵn sàng in + toàn bộ báo cáo"},
]
SCOPE = {s["key"]: s for s in SCOPES}

_SCOPE_OVERRIDES = {
    "termbase": {"workflow": {"revise": False, "edit": False, "consistency": False},
                 "quality": {"independent_eval": False, "fidelity_audit": False}, "proof": {"enabled": False},
                 "terminology": {"prepass": True}},
    "draft": {"workflow": {"draft": True, "revise": False, "edit": False, "consistency": False},
              "translation": {"max_refine_rounds": 0, "web_research": False},
              "quality": {"independent_eval": False, "fidelity_audit": False, "strict_certify": False},
              "proof": {"enabled": True, "vision": False}, "memory": {"auto_enrich": False},
              "escalation": {"enabled": False}},
    "edit": {"workflow": {"revise": False, "edit": True, "consistency": True},
             "quality": {"judges": ["linguistic"]}, "proof": {"enabled": True, "vision": False}},
    "revise": {"workflow": {"revise": True, "edit": True, "consistency": True},
               "quality": {"judges": ["clinical", "linguistic"]}, "proof": {"enabled": True, "vision": False}},
    "publish": {"workflow": {"revise": True, "edit": True, "consistency": True},
                "quality": {"judges": ["clinical", "linguistic"]}, "proof": {"enabled": True, "vision": True}},
}


@functools.lru_cache(maxsize=1)
def _vram() -> float:
    from .hardware import detect
    return max((g["vram_gb"] for g in detect().get("gpus", [])), default=0.0)


def local_base(cfg: Config) -> str:
    """Hồ sơ nền cho phương thức local: cấu hình plans.local_profile (auto → theo VRAM của máy)."""
    choice = cfg.get_path("plans.local_profile", "auto")
    if choice and choice != "auto":
        return choice
    return "local_pro" if _vram() >= 23 else "local_cascade"


def base_profile(cfg: Config, engine: str, scope: str) -> str:
    if engine == "api":
        return "draft" if scope == "draft" else cfg.get_path("plans.api_profile", "premium")
    return local_base(cfg)


SPEEDS = {None: "Tiêu chuẩn", 16: "Nhanh · 16 luồng", 32: "Tối đa · 32 luồng"}  # số luồng API song song


def plan_name(engine: str, scope: str, workers: int | None = None) -> str:
    return f"plan:{engine}:{scope}" + (f":w{workers}" if workers else "")


def parse_full(name: str) -> tuple[str, str, int | None]:
    parts = name.split(":")
    if len(parts) not in (3, 4) or parts[0] != "plan":
        raise ValueError(f"Gói không hợp lệ: {name}")
    engine, scope = parts[1], parts[2]
    workers = int(parts[3][1:]) if len(parts) == 4 and parts[3].startswith("w") and parts[3][1:].isdigit() else None
    if engine not in ENGINES or scope not in SCOPE:
        raise ValueError(f"Gói không hợp lệ: {name} (phương thức: {', '.join(ENGINES)}; phạm vi: {', '.join(SCOPE)})")
    return engine, scope, workers


def parse(name: str) -> tuple[str, str]:
    return parse_full(name)[:2]


def is_plan(name: str | None) -> bool:
    return bool(name) and str(name).startswith("plan:")


def plan_label(name: str) -> str:
    engine, scope, workers = parse_full(name)
    return f"{ENGINES[engine]['short']} · {SCOPE[scope]['label']}" + (f" · {workers} luồng" if workers else "")


def plan_config(cfg: Config, name: str) -> Config:
    from .config import apply_profile
    engine, scope, workers = parse_full(name)
    base = base_profile(cfg, engine, scope)
    out = apply_profile(cfg, base)
    out = Config(_deep_merge(dict(out), _SCOPE_OVERRIDES[scope]))
    out["workflow"]["scope"] = scope
    if workers:
        out["translation"]["workers"] = workers
    out["active_profile"] = name
    out["plan"] = {"engine": engine, "scope": scope, "base_profile": base}
    return out


def mode_for(name: str) -> str:
    """Chế độ chạy của hàng đợi: gói termbase chỉ quét thuật ngữ."""
    return "scan_terms" if is_plan(name) and parse(name)[1] == "termbase" else "translate"


def matrix(cfg: Config, counts: dict, db=None) -> dict:
    """Dự báo chi phí/thời gian cho mọi ô (phương thức × phạm vi) từ số liệu đã quét.

    counts: pages, chars (tổng ký tự cần xử lý), weighted_chars (sau khi trừ bộ nhớ dịch/lặp), scanned, images.
    """
    from .translator import estimate_from_counts
    out: dict = {}
    for engine in ENGINES:
        for s in SCOPES:
            pc = plan_config(cfg, plan_name(engine, s["key"]))
            chars = counts["chars"] if s["key"] == "termbase" else counts["weighted_chars"]
            est = estimate_from_counts(counts["pages"], chars, counts["scanned"], counts["images"], pc, db)
            est["base_profile"] = pc["plan"]["base_profile"]
            est["local_model"] = pc.get_path("llm.local.model") if engine == "local" else None
            out[(engine, s["key"])] = est
    return out


def friendly(model: str) -> str:
    """claude-opus-5-5 → Claude Opus 5.5"""
    m = str(model or "")
    if m.startswith("claude-"):
        parts = m.split("-")
        return "Claude " + parts[1].capitalize() + (" " + ".".join(parts[2:]) if len(parts) > 2 else "")
    return m


def pipeline(pc: Config) -> list[tuple[str, str]]:
    """Các công đoạn sẽ chạy cho cấu hình gói đã áp + ai thực hiện (để hiển thị & bàn giao minh bạch)."""
    plan = pc.get("plan") or {}
    engine, scope = plan.get("engine", "api"), plan.get("scope", "publish")
    get = pc.get_path
    routes = get("llm.routes", {}) or {}
    local = get("llm.provider") in ("local", "medcrab") or engine == "local"
    model = get("llm.local.model") if local else get("llm.model")
    claude = friendly(get("llm.model", "claude-opus-5-5")) if not local else "Claude API"
    who = (lambda task: claude if routes.get(task) == "anthropic" or not local
           else (get("llm.local_judge.model") if routes.get(task) == "local_judge" else model))
    steps = [("Phân tích bố cục, OCR trang scan", "Máy bạn")]
    steps.append(("Đọc tổng quan & quét thuật ngữ toàn văn", who("termprep")))
    if get("translation.web_research", True):
        steps.append(("Tra cứu web thuật ngữ chưa chắc", "Claude API + web"))
    if scope == "termbase":
        steps.append(("Xuất termbase Excel/TBX → chuyên gia kiểm tra & khoá", "Bạn / chuyên gia"))
        return steps
    steps.append(("Dịch theo termbase, giữ công thức & ký hiệu", who("translate")))
    if get("workflow.revise", True):
        steps.append(("Hiệu đính chuyên môn (đối chiếu bản gốc)", who("revise")))
    if get("workflow.edit", True):
        steps.append(("Biên tập ngôn ngữ", who("review")))
    if get("quality.independent_eval", True):
        n = len(get("quality.judges", []) or [])
        steps.append((f"Hội đồng MQM {n} giám khảo + kiểm toán trung thành", who("evaluate")))
    if local and get("escalation.enabled", False):
        steps.append(("Leo thang đoạn khó + kiểm tra mẫu ngẫu nhiên", "Claude API"))
    if get("workflow.consistency", True):
        steps.append(("Biên tập thống nhất toàn văn", who("consistency")))
    if get("layout.translate_images", True):
        steps.append(("Nhận dạng & dịch chữ trong hình, biểu đồ", who("translate")))
    steps.append(("Dàn trang PDF tiếng Việt", "Máy bạn"))
    if get("proof.enabled", True) and get("proof.vision", True):
        steps.append(("Đọc morat trên trang & sửa morat", who("proof")))
    elif get("proof.enabled", True):
        steps.append(("Kiểm tra bố cục tự động (tràn chữ, chồng lấn)", "Máy bạn"))
    if not get("workflow.draft", False):
        steps.append(("Làm giàu bộ nhớ dịch & báo cáo chất lượng", "Máy bạn"))
    return steps
