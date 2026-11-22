@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "OUT=diagnose.txt"
echo Collecting information about this computer (about 30 seconds)...

echo === Sheet Check diagnostics === > "%OUT%"
echo Folder: %CD% >> "%OUT%"
echo Windows: >> "%OUT%"
ver >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo === Python versions installed (py -0) === >> "%OUT%"
py -0 >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo === python on the PATH === >> "%OUT%"
where python >> "%OUT%" 2>&1
python --version >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo === The app's own environment (.venv) === >> "%OUT%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >> "%OUT%" 2>&1
  ".venv\Scripts\python.exe" -m pip list --disable-pip-version-check >> "%OUT%" 2>&1
) else (
  echo not created yet >> "%OUT%"
)

echo. >> "%OUT%"
echo === Ollama === >> "%OUT%"
ollama --version >> "%OUT%" 2>&1
ollama list >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo === Memory and disk === >> "%OUT%"
powershell -NoProfile -Command "$o=Get-CimInstance Win32_OperatingSystem; 'RAM total GB: ' + [math]::Round($o.TotalVisibleMemorySize/1MB,1); 'RAM free GB: ' + [math]::Round($o.FreePhysicalMemory/1MB,1); 'Disk free GB (this drive): ' + [math]::Round((Get-PSDrive ($pwd.Drive.Name)).Free/1GB,1); 'CPU: ' + (Get-CimInstance Win32_Processor | Select-Object -First 1).Name" >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo === Internet (any HTTP number means the site is reachable) === >> "%OUT%"
powershell -NoProfile -Command "foreach($u in 'https://pypi.org','https://files.pythonhosted.org','https://ollama.com','https://registry.ollama.ai'){ try { $r=Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 15; $u + '  reachable (HTTP ' + [int]$r.StatusCode + ')' } catch { if ($_.Exception.Response) { $u + '  reachable (HTTP ' + [int]$_.Exception.Response.StatusCode + ')' } else { $u + '  NOT REACHABLE: ' + $_.Exception.Message } } }" >> "%OUT%" 2>&1

echo.
type "%OUT%"
echo.
echo ==================================================
echo   Done. Send the file diagnose.txt (in this folder) to the person helping you.
echo   It contains the Windows user name inside folder paths, and nothing else personal.
echo ==================================================
pause
