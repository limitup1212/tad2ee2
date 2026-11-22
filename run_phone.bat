@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python.bat"
if not defined PY goto :notready
echo.
echo The app opens on this computer at http://localhost:8501
echo On the input page, open "the phone" section and scan the QR code with the phone camera.
echo The phone must be on the same Wi-Fi as this computer.
echo.
echo If Windows asks about the firewall, choose "Allow" for PRIVATE networks.
echo Anyone on this Wi-Fi can open the app while this window is running.
echo Keep this window open while using the app. Close it to stop.
echo.
rem Open the browser ourselves after a few seconds. Starting Streamlit with headless=false
rem would instead stop at a first-run "Email:" question and look frozen.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:8501'"
%PY% -m streamlit run app.py --server.address 0.0.0.0 --server.headless true
pause
exit /b 0

:notready
echo.
echo   The app is not set up on this computer yet.
echo   Run  setup.bat  once (it installs Python's libraries and the model), then run_phone.bat again.
echo   If setup.bat says Python was not found: install Python from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" on the first installer screen.
echo.
pause
exit /b 1
