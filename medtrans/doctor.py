"""KIỂM TRA HỆ THỐNG trước khi chạy: thư viện, khoá API (gọi thử), Tesseract, font tiếng Việt, ổ đĩa, CSDL, model local.

Mỗi mục: (tên, trạng thái ok|warn|fail, chi tiết, cách khắc phục). "fail" = chưa chạy được; "warn" = chạy được nhưng
thiếu một phần (ví dụ không có Tesseract thì trang scan không đọc được).
"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
from pathlib import Path

from .config import ROOT, Config

PKGS = ["anthropic", "pymupdf", "streamlit", "rapidfuzz", "yaml", "PIL", "pytesseract", "openpyxl", "pandas", "httpx2"]


def _item(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_api_key(cfg: Config, timeout: float = 20.0) -> dict:
    """Gọi thử API (lấy thông tin model – không tốn token) để xác nhận khoá hợp lệ và model dùng được."""
    if os.environ.get("MEDTRANS_PROVIDER"):
        return _item("Claude API", "ok", f"Chế độ trình diễn ({os.environ['MEDTRANS_PROVIDER']}) – không gọi API")
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not key or key.endswith("..."):
        return _item("Claude API", "fail", "Chưa có ANTHROPIC_API_KEY",
                     "Nhập khoá ở mục Cấu hình & hệ thống, hoặc điền vào file .env (xem .env.example)")
    model = cfg.get_path("llm.model", "claude-opus-5-5")
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=timeout, max_retries=1)
        m = client.models.retrieve(model)
        return _item("Claude API", "ok", f"Khoá hợp lệ · model {getattr(m, 'display_name', model)} sẵn sàng")
    except Exception as e:  # noqa: BLE001
        import anthropic
        if isinstance(e, anthropic.AuthenticationError):
            return _item("Claude API", "fail", "Khoá API không hợp lệ hoặc đã bị thu hồi",
                         "Tạo khoá mới tại console.anthropic.com → API Keys")
        if isinstance(e, anthropic.PermissionDeniedError):
            return _item("Claude API", "fail", "Khoá không có quyền dùng model này",
                         "Kiểm tra workspace/quyền của khoá trên console.anthropic.com")
        if isinstance(e, anthropic.NotFoundError):
            return _item("Claude API", "fail", f"Tài khoản chưa dùng được model {model}",
                         "Đổi llm.model trong config.yaml hoặc liên hệ Anthropic")
        if isinstance(e, anthropic.APIConnectionError):
            return _item("Claude API", "warn", "Không kết nối được api.anthropic.com",
                         "Kiểm tra Internet / tường lửa / proxy của máy")
        return _item("Claude API", "warn", f"Chưa xác nhận được khoá: {str(e)[:160]}")


def run(cfg: Config, call_api: bool = True) -> list[dict]:
    out = []
    v = sys.version_info
    out.append(_item("Python", "ok" if v >= (3, 10) else "fail", platform.python_version(),
                     "" if v >= (3, 10) else "Cài Python 3.10 trở lên"))
    missing = []
    for p in PKGS:
        try:
            importlib.import_module(p)
        except Exception:  # noqa: BLE001
            missing.append(p)
    out.append(_item("Thư viện", "fail" if missing else "ok",
                     "Đủ" if not missing else f"Thiếu: {', '.join(missing)}",
                     "Chạy lại run_windows.bat / run_mac_linux.sh, hoặc: pip install -r requirements.txt"))
    if call_api:
        out.append(check_api_key(cfg))
    from .scan import tesseract_available, tesseract_cmd
    if tesseract_available():
        import pytesseract
        out.append(_item("Tesseract OCR", "ok", f"{pytesseract.get_tesseract_version()} · {tesseract_cmd()}"))
    else:
        out.append(_item("Tesseract OCR", "warn",
                         "Chưa cài – trang scan sẽ không đọc được chữ; chữ trong hình do AI đọc (tốn thêm token)",
                         "Windows: cài bản UB Mannheim (github.com/UB-Mannheim/tesseract/wiki) · macOS: brew install "
                         "tesseract · Ubuntu: sudo apt install tesseract-ocr"))
    try:
        from .pdf_render import find_fonts
        f = find_fonts(cfg.get("layout", {}))
        out.append(_item("Font tiếng Việt", "ok", f"{Path(f.serif[0]).name} / {Path(f.sans[0]).name}"))
    except Exception as e:  # noqa: BLE001
        out.append(_item("Font tiếng Việt", "fail", str(e)[:200],
                         "Khai báo layout.serif_font / layout.sans_font trong config.yaml"))
    ws = cfg.resolve("workspace")
    try:
        ws.mkdir(parents=True, exist_ok=True)
        probe = ws / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        free = shutil.disk_usage(ws).free / 2 ** 30
        out.append(_item("Ổ đĩa", "ok" if free >= 5 else "warn", f"Còn trống {free:.1f} GB tại {ws}",
                         "" if free >= 5 else "Nên trống ≥ 5 GB cho sách lớn (ảnh trang, bản dịch, báo cáo)"))
    except Exception as e:  # noqa: BLE001
        out.append(_item("Ổ đĩa", "fail", f"Không ghi được vào {ws}: {e}", "Cấp quyền ghi cho thư mục ứng dụng"))
    try:
        from .db import Database
        db = Database(cfg.resolve(cfg.get_path("memory.db_path", "workspace/medtrans.db")))
        n = db.query("SELECT COUNT(*) n FROM glossary")[0]["n"]
        out.append(_item("Cơ sở dữ liệu", "ok" if n else "warn", f"{n} thuật ngữ trong kho",
                         "" if n else "Chạy: python -m medtrans init (nạp bộ thuật ngữ mẫu)"))
    except Exception as e:  # noqa: BLE001
        out.append(_item("Cơ sở dữ liệu", "fail", str(e)[:200]))
    local_needed = cfg.get_path("plans.default_engine", "api") == "local" or cfg.get_path("llm.provider") == "local"
    url = (cfg.get_path("llm.local.base_url", "") or "").rstrip("/")
    try:
        import httpx2
        r = httpx2.get(url + "/models", timeout=2, trust_env=False)
        ms = [m.get("id", "") for m in r.json().get("data", [])]
        out.append(_item("AI local (tuỳ chọn)", "ok", f"{url} · {', '.join(ms[:4]) or 'chưa có model'}"))
    except Exception:  # noqa: BLE001
        out.append(_item("AI local (tuỳ chọn)", "warn" if local_needed else "ok",
                         "Chưa chạy – chỉ cần khi dùng phương thức AI Local + API",
                         "Cài Ollama (ollama.com) rồi: ollama pull " + str(cfg.get_path("llm.local.model", "qwen3:8b"))))
    return out


def ready(items: list[dict]) -> bool:
    return not any(i["status"] == "fail" for i in items)


def save_api_key(key: str) -> Path:
    """Ghi/ cập nhật ANTHROPIC_API_KEY trong .env (không in khoá ra màn hình / nhật ký)."""
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith("ANTHROPIC_API_KEY=")]
    lines.insert(0, f"ANTHROPIC_API_KEY={key.strip()}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key.strip()
    return env
