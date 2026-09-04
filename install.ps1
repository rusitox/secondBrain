# secondBrain Installer for Windows
# Run with: powershell -ExecutionPolicy Bypass -File install.ps1

Write-Host "=== secondBrain Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found. Installing via winget..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "Python installation failed. Please install Python 3.8+ manually." -ForegroundColor Red
        exit 1
    }
}
$pyVersion = python --version 2>&1
Write-Host "  Python: $pyVersion" -ForegroundColor Green

# 2. Check Docker
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Host ""
    Write-Host "Docker not found. Installing via winget..." -ForegroundColor Yellow
    winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Write-Host ""
    Write-Host "Please start Docker Desktop and re-run this script." -ForegroundColor Yellow
    exit 1
}

# Check Docker daemon
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Docker is installed but not running." -ForegroundColor Yellow
    Write-Host "Please start Docker Desktop and re-run this script." -ForegroundColor Yellow
    exit 1
}
$dockerVersion = docker --version 2>&1
Write-Host "  Docker: $dockerVersion" -ForegroundColor Green

# 3. Install Python dependencies
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
python -m pip install -r requirements.txt --quiet 2>$null
Write-Host "  Dependencies installed" -ForegroundColor Green

# 4. Delegate to CLI installer
Write-Host ""
python -m cli install
