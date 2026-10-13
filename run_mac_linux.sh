#!/usr/bin/env bash
# ======================================================================
#  DMAG MedTrans – khởi động trên macOS / Linux:  ./run_mac_linux.sh
#  Lần đầu: tự tạo môi trường, cài thư viện, nạp thuật ngữ mẫu, kiểm tra hệ thống.
# ======================================================================
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[LỖI] Chưa có Python 3.10+. macOS: brew install python · Ubuntu: sudo apt install python3 python3-venv"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "[1/4] Đang tạo môi trường .venv ..."
  "$PY" -m venv .venv
fi
VPY=.venv/bin/python

if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "[2/4] Đang cài thư viện (lần đầu mất vài phút, cần Internet) ..."
  "$VPY" -m pip install --upgrade pip >/dev/null
  "$VPY" -m pip install -r requirements.txt
  cp requirements.txt .venv/requirements.installed
fi

[ -f .env ] || cp .env.example .env
echo "[3/4] Khởi tạo cơ sở dữ liệu ..."
"$VPY" -m medtrans init
echo "[4/4] Kiểm tra hệ thống ..."
"$VPY" -m medtrans doctor --offline || true

echo
echo "Mở giao diện tại http://localhost:8501 (Ctrl+C để dừng)."
echo "Lần đầu: vào mục 'Cấu hình & hệ thống' để nhập Claude API key."
exec "$VPY" -m medtrans ui
