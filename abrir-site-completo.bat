@echo off
cd /d "%~dp0"

taskkill /FI "WINDOWTITLE eq Servidor Barravento" /T /F >nul 2>nul

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [Regex]::Escape((Get-Location).Path); Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('node.exe','cmd.exe') -and $_.CommandLine -match $root -and $_.CommandLine -match 'server\.js|npm-cli\.js.+start|cmd.+npm start' } | Select-Object -ExpandProperty ProcessId"`) do (
  taskkill /PID %%P /F >nul 2>nul
)

start "Servidor Barravento" cmd /k "cd /d ""%~dp0"" && npm start"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:3000/
