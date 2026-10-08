@echo off
cd /d "%~dp0"
python server\app.py --practice %*
pause
