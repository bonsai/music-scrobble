#!/bin/powershell
# start.ps1 – 一度起動するだけでfire生成→fastapi→ブラウザ表示まで自動化

$ErrorActionPreference = "Continue"
Write-Host "=== Houdini Fire Auto Start ===" -ForegroundColor Cyan
Write-Host ""

# 1) 依存チェック & インストール
$pkgNames = @("fastapi", "uvicorn[standard]", "pyyaml", "fastmcp")
foreach ($name in $pkgNames) {
    $mod = ($name -replace '\[.*?\]', '') -replace '\[','' -replace '\]',''
    if (Get-Module -ListAvailable -Name $mod -ErrorAction SilentlyContinue) {
        Write-Host "✓ $name already installed" -ForegroundColor Green
    } else {
        Write-Host "  Installing $name..." -ForegroundColor Yellow
        python -m pip install --quiet $name
    }
}

# 2) fire.yaml → .bgeo 生成
Write-Host "" -ForegroundColor Cyan
Write-Host "[1/3] Generating fire simulation..." -ForegroundColor Yellow
python pyro.py

if (-not (Test-Path "./fire.bgeo")) {
    Write-Host "✗ fire.bgeo 生成に失敗しました" -ForegroundColor Red
    exit 1
}
Write-Host "✓ fire.bgeo 生成完了" -ForegroundColor Green

# 3) FastAPI 起動 (バックグラウンド)
Write-Host "" -ForegroundColor Cyan
Write-Host "[2/3] Starting FastAPI..." -ForegroundColor Yellow
Start-Process python -ArgumentList "main.py" -WindowStyle Normal
Start-Sleep -Seconds 3

# 4) ブラウザ起動
Write-Host ""
Write-Host "[3/3] Opening browser..." -ForegroundColor Yellow
$browserPath = ""
$browserPaths = @(
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
)
foreach ($p in $browserPaths) {
    if (Test-Path $p) { $browserPath = $p; break }
}

if ($browserPath) {
    Start-Process $browserPath -ArgumentList "http://localhost:8000/"
    Write-Host "  Browser launched: $browserPath" -ForegroundColor Green
} else {
    Write-Host "  No supported browser found. Visit http://localhost:8000/ manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Running at http://localhost:8000 ===" -ForegroundColor Cyan
Write-Host " Press Ctrl+C or close terminal to stop." -ForegroundColor White

# 維持ループ
while ($true) {
    Start-Sleep -Seconds 1
}
