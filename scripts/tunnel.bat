@echo off
REM Скрипт для запуска SSH туннелей через serveo.net
REM Использование:
REM   scripts\tunnel.bat frontend  - туннель для Dioxus (8080)
REM   scripts\tunnel.bat api       - туннель для FastAPI (8000)

set MODE=%1
if "%MODE%"=="" set MODE=frontend

if "%MODE%"=="frontend" (
    set PORT=8080
    set NAME=Frontend (Dioxus)
    set ENV_VAR=WEBAPP_BASE_URL
) else if "%MODE%"=="f" (
    set PORT=8080
    set NAME=Frontend (Dioxus)
    set ENV_VAR=WEBAPP_BASE_URL
) else if "%MODE%"=="api" (
    set PORT=8000
    set NAME=API (FastAPI)
    set ENV_VAR=WEBAPP_API_URL
) else if "%MODE%"=="a" (
    set PORT=8000
    set NAME=API (FastAPI)
    set ENV_VAR=WEBAPP_API_URL
) else (
    set PORT=%MODE%
    set NAME=Custom
    set ENV_VAR=???
)

echo.
echo ===================================================
echo   SSH Tunnel via serveo.net
echo ===================================================
echo.
echo   Service: %NAME%
echo   Local port: %PORT%
echo.
echo   IMPORTANT: Copy the URL and set in .env:
echo   %ENV_VAR%=https://xxxxx.serveo.net
echo.
echo   For two tunnels, run in separate terminals:
echo     scripts\tunnel.bat frontend
echo     scripts\tunnel.bat api
echo.
echo   Press Ctrl+C to stop the tunnel
echo ===================================================
echo.

ssh -R 80:localhost:%PORT% serveo.net
