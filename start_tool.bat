@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BUILD_LABEL=Phase3-Full-Stable"
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "APP_FILE=%APP_DIR%\app.py"
set "PORT=5000"

echo.
echo ============================================================
echo   IFMS Report Analyzer
echo   Build: %BUILD_LABEL%
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "delims=" %%p in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%p"
    goto :python_found
)
:python_found

echo App folder: %APP_DIR%
echo Python executable: %PYTHON_EXE%
echo app.py path: %APP_FILE%
echo.

echo Installing required packages...
python -m pip install -r "%APP_DIR%\requirements.txt" --quiet
echo Done.
echo.

:check_port
set "PORT_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    set "PORT_PID=%%p"
)

if defined PORT_PID (
    echo Port %PORT% is already occupied by PID !PORT_PID!.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"ProcessId=!PORT_PID!\" | Select-Object ProcessId,Name,CommandLine | Format-List"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $v=Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/api/version' -TimeoutSec 3; if ($v.build_label -ne '%BUILD_LABEL%') { Write-Host '[WARNING] Existing /api/version build label is' $v.build_label ', expected %BUILD_LABEL%.' } else { Write-Host '[OK] Existing server reports expected build label.' } } catch { Write-Host '[WARNING] Existing /api/version did not respond.' }"
    echo Health Check URL: http://127.0.0.1:%PORT%/api/v3/health_check
    echo.
    set /p "CHOICE=Type S to stop this app process, P to choose another port, or Q to quit: "
    if /I "!CHOICE!"=="Q" exit /b 1
    if /I "!CHOICE!"=="P" (
        set /p "PORT=Enter port number: "
        goto :check_port
    )
    if /I "!CHOICE!"=="S" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=!PORT_PID!\"; if ($p.CommandLine -match 'app\.py') { Stop-Process -Id !PORT_PID! -Force; Write-Host 'Stopped app process PID !PORT_PID!.' } else { Write-Host '[WARNING] PID !PORT_PID! does not look like app.py. Not stopped.'; exit 2 }"
        if errorlevel 2 (
            pause
            exit /b 1
        )
        timeout /t 2 >nul
        goto :check_port
    )
    echo Unknown choice.
    goto :check_port
)

for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } ^| Select-Object -First 1 -ExpandProperty IPAddress)" 2^>nul') do set "LAN_IP=%%i"
if not defined LAN_IP set "LAN_IP=Unavailable"

echo Selected port: %PORT%
echo Local URL: http://127.0.0.1:%PORT%
if "%LAN_IP%"=="Unavailable" (
    echo LAN URL: Unavailable
) else (
    echo LAN URL: http://%LAN_IP%:%PORT%
)
echo API Version URL: http://127.0.0.1:%PORT%/api/version
echo Health Check URL: http://127.0.0.1:%PORT%/api/v3/health_check
echo.
echo If an old browser tab is open, refresh it after this server starts.
echo Press Ctrl+C to stop the server.
echo.

set "PORT=%PORT%"
python "%APP_FILE%"
pause
