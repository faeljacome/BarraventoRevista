@echo off
cd /d "%~dp0"

start "Servidor Barravento" cmd /k npm start
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:3000/
