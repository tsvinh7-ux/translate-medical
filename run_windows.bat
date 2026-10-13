@echo off
REM ======================================================================
REM  DMAG MedTrans - khoi dong tren Windows (nhay dup de chay)
REM  Lan dau: tu tao moi truong, cai thu vien, nap thuat ngu mau, kiem tra he thong.
REM ======================================================================
setlocal
title DMAG MedTrans
cd /d "%~dp0"

REM --- 1. Python 3.10+
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul || goto :nopython

REM --- 2. Moi truong rieng .venv
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Dang tao moi truong .venv ...
  %PY% -m venv .venv || goto :fail
)
set "VPY=.venv\Scripts\python.exe"

REM --- 3. Thu vien (tu cai lai khi requirements.txt thay doi)
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo [2/4] Dang cai thu vien - lan dau mat vai phut, can Internet ...
  "%VPY%" -m pip install --upgrade pip >nul 2>nul
  "%VPY%" -m pip install -r requirements.txt || goto :fail
  copy /y requirements.txt ".venv\requirements.installed" >nul
)

REM --- 4. Cau hinh khoa API va CSDL
if not exist ".env" copy ".env.example" ".env" >nul
echo [3/4] Khoi tao co so du lieu ...
"%VPY%" -m medtrans init
echo [4/4] Kiem tra he thong ...
"%VPY%" -m medtrans doctor --offline

echo.
echo Mo giao dien tai http://localhost:8501  (dong cua so nay de dung chuong trinh)
echo Lan dau: vao muc "Cau hinh va he thong" de nhap Claude API key.
"%VPY%" -m medtrans ui
goto :eof

:nopython
echo [LOI] Chua cai Python 3.10 tro len.
echo Tai tai https://www.python.org/downloads/  - khi cai nho tick "Add Python to PATH", sau do chay lai file nay.
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo [LOI] Cai dat that bai. Kiem tra ket noi Internet roi chay lai file nay.
pause
exit /b 1
