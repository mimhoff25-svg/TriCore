# Starts the TriCore Scanner desktop app on Windows.
# This launcher opens TriCore in a desktop app window. The Electron app starts
# the local FastAPI backend itself and loads the built dashboard from disk.

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$RtlSdrDllDirs = @(
    (Join-Path $ProjectRoot "..\..\sdrpp_windows_x64"),
    (Join-Path $ProjectRoot "..\..\sdrpp_windows_x64\sdrpp_windows_x64"),
    (Join-Path $ProjectRoot "..\..\sdrpp_windows_x64\DSDPlus"),
    "C:\Program Files\PothosSDR\bin",
    "C:\rtl-sdr",
    "C:\Users\mimho\Downloads\SDRPlusPlus\sdrpp_windows_x64",
    "C:\Program Files\rtl-sdr",
    "C:\Program Files (x86)\rtl-sdr"
)

if (-not (Test-Path $PythonExe)) {
    Write-Host "Python virtual environment was not found." -ForegroundColor Yellow
    Write-Host "Run backend setup first:" -ForegroundColor Yellow
    Write-Host "  cd $BackendDir"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pip install -r requirements.txt"
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "Frontend dependencies were not found. Installing now..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install --strict-ssl=false --ignore-scripts --no-audit --no-fund
    Pop-Location
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules\electron"))) {
    Write-Host "Electron desktop shell was not found. Installing now..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install --strict-ssl=false --ignore-scripts --no-audit --no-fund
    Pop-Location
}

foreach ($DllDir in $RtlSdrDllDirs) {
    if (Test-Path (Join-Path $DllDir "rtlsdr.dll")) {
        $env:PATH = "$DllDir;$env:PATH"
        Write-Host "RTL-SDR DLL path enabled: $DllDir" -ForegroundColor Green
    }
}

if (Test-Path Env:ELECTRON_RUN_AS_NODE) {
    Remove-Item Env:ELECTRON_RUN_AS_NODE
}

Write-Host "Opening TriCore Scanner desktop app..." -ForegroundColor Green
Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run desktop" `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden

Write-Host "TriCore Scanner desktop app is starting." -ForegroundColor Green
