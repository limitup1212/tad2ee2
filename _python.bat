@echo off
rem Finds a Python that can run the app and leaves it in the variable PY.
rem Used by run.bat and run_phone.bat. PY stays empty when none works.
set "PY="

rem 1. The app's own environment made by setup.bat (ignored if it was copied from another computer).
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import streamlit, ollama, pypdfium2" >nul 2>nul
  if not errorlevel 1 set "PY=.venv\Scripts\python.exe"
)
if defined PY exit /b 0

rem 2. Python on the PATH.
python -c "import streamlit, ollama, pypdfium2" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY exit /b 0

rem 3. The Windows "py" launcher.
py -3 -c "import streamlit, ollama, pypdfium2" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
exit /b 0
