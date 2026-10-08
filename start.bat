@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.11+ is needed. & pause & exit /b 1)
python server\app.py %*
pause
