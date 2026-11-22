@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==================================================
echo   Sheet Check  -  first-time setup
echo   (run this once on a new computer)
echo ==================================================
echo.

set "STEP=0/5 - before starting"
if not exist "requirements.txt" (
  echo   The app files were not found next to setup.bat.
  echo   If you opened the zip file, the files were NOT extracted: right-click the zip,
  echo   choose "Extract All...", open the new folder, and run setup.bat from there.
  goto :fail
)

set "STEP=1/5 - checking Python"
echo [1/5] Checking Python...
rem The app needs Python 3.11 - 3.14 (3.13 is the tested one). Several versions can be installed
rem side by side; the "py" launcher lets us pick a suitable one even if "python" is an old one.
set "BASEPY="
for %%v in (3.13 3.12 3.11 3.14) do (
  if not defined BASEPY (
    py -%%v -c "import sys" >nul 2>nul
    if not errorlevel 1 set "BASEPY=py -%%v"
  )
)
if not defined BASEPY (
  python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>nul
  if not errorlevel 1 set "BASEPY=python"
)
if not defined BASEPY (
  echo   No Python 3.11 - 3.14 was found on this computer.
  echo   Versions found here:
  py -0 2>nul
  python --version 2>nul
  echo.
  echo   Install Python 3.13 from https://www.python.org/downloads/ - it can stay next to the
  echo   old version, nothing is removed. IMPORTANT: tick "Add python.exe to PATH" on the
  echo   first installer screen. Then close this window and run setup.bat again.
  goto :fail
)
echo   Using: %BASEPY%
%BASEPY% --version

echo.
set "STEP=2/5 - installing the app's libraries"
echo [2/5] Installing the app's libraries into the folder .venv ...
rem Some library files sit about 160 characters deep inside .venv, and Windows stops at 260.
%BASEPY% -c "import os, sys; sys.exit(1 if len(os.getcwd()) > 90 else 0)"
if errorlevel 1 goto :longpath
rem An environment copied from another computer points at a Python that is not here: rebuild it.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo   The existing .venv does not work on this computer - rebuilding it.
    rmdir /s /q .venv
  )
)
if not exist ".venv\Scripts\python.exe" (
  %BASEPY% -m venv .venv
  if errorlevel 1 (
    echo   Could not create the private Python environment ^(.venv^).
    goto :fail
  )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 (
  echo   Could not reach the Python package server. Check the internet connection.
  goto :fail
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo   Could not install the libraries. The lines above say which one failed.
  echo   Common causes: no internet, a firewall or proxy blocking pypi.org, or a full disk.
  goto :fail
)
echo   Libraries installed.

echo.
set "STEP=3/5 - checking Ollama"
echo [3/5] Checking Ollama (runs the AI model on this computer)...
ollama --version >nul 2>nul
if errorlevel 1 (
  echo   Ollama was not found.
  echo   Install it from https://ollama.com/download . If you just installed it, close this
  echo   window, open it again ^(so Windows sees the new program^), and run setup.bat again.
  goto :fail
)
ollama --version

echo.
set "STEP=4/5 - downloading the model"
set MODEL=qwen3-vl:4b-instruct
for /f "delims=" %%m in ('.venv\Scripts\python.exe scripts\model_name.py') do set MODEL=%%m
echo [4/5] Downloading the model %MODEL% (about 3.3 GB, one time only)...
echo   This can take a long time on a slow connection. It resumes if interrupted.
ollama pull %MODEL%
if errorlevel 1 (
  echo   The download did not finish. Make sure the Ollama icon is near the clock ^(open Ollama
  echo   from the Start menu if not^) and that the internet works, then run setup.bat again.
  goto :fail
)

echo.
set "STEP=5/5 - testing the model"
echo [5/5] Testing that the model reads an Arabic test sheet on this computer...
echo   (a few minutes on a computer without a graphics card)
".venv\Scripts\python.exe" scripts\check_model.py
if errorlevel 1 (
  echo.
  echo   The model test did not pass. The app is installed, so you can still try run.bat,
  echo   but read the messages above: "memory" means this computer has too little free RAM
  echo   ^(close other programs and try again^). Run diagnose.bat and send the file it makes.
  echo.
  echo ==================================================
  echo   Setup finished with a WARNING ^(model test failed^).
  echo ==================================================
  pause
  exit /b 2
)

echo.
echo ==================================================
echo   Setup finished.
echo   Start the app with run.bat  (or run_phone.bat to use the phone camera).
echo ==================================================
pause
exit /b 0

:longpath
rem Kept outside any ( ) block: a folder name such as "tadqeeq (1)" would break the block.
echo   This folder's path is too long for Windows (some library files would pass the
echo   260-character limit):
echo     "%CD%"
echo   Move the app folder somewhere short, for example C:\tadqeeq , and run setup.bat there.
goto :fail

:fail
echo.
echo   Setup stopped at step %STEP%.
echo   Fix the problem above and run setup.bat again.
echo   If you cannot fix it: run diagnose.bat and send the file diagnose.txt it creates.
pause
exit /b 1
