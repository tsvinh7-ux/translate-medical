"""Đọc cấu hình từ config.yaml và .env."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(dict):
    """Dict có truy cập dạng cfg.get_path("llm.model")."""

    def get_path(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    _load_dotenv()
    data = yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8")) or {}
    if overrides:
        data = _deep_merge(data, overrides)
    if os.environ.get("MEDTRANS_DB"):  # CSDL riêng (kiểm thử / nhiều không gian làm việc)
        data.setdefault("memory", {})["db_path"] = os.environ["MEDTRANS_DB"]
    if os.environ.get("MEDTRANS_PROVIDER"):  # chế độ trình diễn / kiểm thử: MEDTRANS_PROVIDER=mock
        data.setdefault("llm", {})["provider"] = os.environ["MEDTRANS_PROVIDER"]
    return Config(data)


PROFILE_ORDER = ["draft", "economy", "balanced", "premium", "local_fast", "local_quality", "hybrid"]


def profiles(cfg: Config) -> dict[str, dict]:
    return cfg.get("profiles") or {}


def apply_profile(cfg: Config, name: str | None) -> Config:
    """Trả về cấu hình đã áp hồ sơ chất lượng/chi phí (không sửa cfg gốc)."""
    name = name or cfg.get("default_profile", "premium")
    prof = profiles(cfg).get(name)
    if prof is None:
        raise ValueError(f"Không có hồ sơ '{name}'. Hiện có: {', '.join(profiles(cfg))}")
    over = {k: v for k, v in prof.items() if k not in ("label", "description")}
    out = Config(_deep_merge(dict(cfg), over))
    out["active_profile"] = name
    return out
