#!/usr/bin/env bash
# Khởi động MedTrans trên macOS / Linux (lần đầu sẽ tự cài thư viện)
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  python -m medtrans init
else
  source .venv/bin/activate
fi
python -m medtrans ui
