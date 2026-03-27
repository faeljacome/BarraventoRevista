@echo off
cd /d "%~dp0"

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [Regex]::Escape((Get-Location).Path); Get-CimInstance Win32_Process -Filter \"name = 'node.exe'\" | Where-Object { $_.CommandLine -match $root -and $_.CommandLine -match 'server\.js|npm-cli\.js.+start' } | Select-Object -ExpandProperty ProcessId"`) do (
  taskkill /PID %%P /F >nul 2>nul
)

start "Servidor Barravento" cmd /k npm start
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:3000/
