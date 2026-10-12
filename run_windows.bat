@echo off
REM Khoi dong MedTrans tren Windows (chay lan dau se tu cai thu vien)
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
  python -m medtrans init
) else (
  call .venv\Scripts\activate
)
python -m streamlit run app.py --server.address localhost
