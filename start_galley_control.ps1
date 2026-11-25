$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeDir = "C:\Users\gagan\.gemini\antigravity\scratch\node-v22.14.0-win-x64"
if (Test-Path $nodeDir) {
    $env:PATH = "$nodeDir;" + $env:PATH
}

Write-Host "Starting Galley Control Backend (FastAPI on http://127.0.0.1:8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --reload --port 8000"

Start-Sleep -Seconds 2

Write-Host "Starting Galley Control Frontend (Vite on http://localhost:5173)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:PATH = '$nodeDir;' + `$env:PATH; cd '$root\frontend'; npm run dev"

Write-Host "Open http://localhost:5173 in your browser once both terminals show ready." -ForegroundColor Green
