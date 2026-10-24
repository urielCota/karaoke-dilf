@echo off
cd /d "%~dp0"
rem Cambia el PIN de control aqui:
set KARAOKE_PIN=1234
python server.py
pause
