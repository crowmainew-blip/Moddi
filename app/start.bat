@echo off
chcp 65001 >nul
title moddi
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "PY="

rem --- หา Python 3.9 ขึ้นไป ---
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""

if not defined PY (
  echo.
  echo  moddi ต้องใช้ Python ซึ่งเครื่องนี้ยังไม่มี
  echo.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo  เปิดหน้าดาวน์โหลด Python ให้แล้ว ตอนติดตั้งให้ติ๊ก "Add python.exe to PATH"
    echo  ติดตั้งเสร็จแล้วดับเบิลคลิก start.bat อีกครั้ง
    start https://www.python.org/downloads/
    pause
    exit /b
  )
  choice /c YN /m " ติดตั้ง Python ให้อัตโนมัติเลยไหม"
  if errorlevel 2 exit /b
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
  ) else (
    echo  ติดตั้งเสร็จแล้ว ปิดหน้าต่างนี้ แล้วดับเบิลคลิก start.bat อีกครั้ง
    pause
    exit /b
  )
)

if not exist "site\index.html" (
  %PY% ..\web\build.py
  if not exist site mkdir site
  copy /y ..\web\site\index.html site\ >nul
  copy /y ..\web\site\catalog.json site\ >nul
  xcopy /e /i /y ..\web\site\mods site\mods >nul
)

echo.
echo  moddi กำลังเปิดในเบราว์เซอร์ ... ปิดหน้าต่างนี้เมื่อเลิกใช้
echo.
%PY% app.py
if errorlevel 1 pause
