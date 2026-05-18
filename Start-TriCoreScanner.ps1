# Starts the TriCore Scanner desktop app on Windows.
# This launcher opens TriCore in a desktop app window. The Electron app starts
# the local FastAPI backend itself and loads the built dashboard from disk.

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$DesktopShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TriCore Scanner.lnk"
$IconPath = Join-Path $FrontendDir "public\icons\tricore.ico"
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

function Get-BootstrapPython {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Command = $py.Source; Arguments = @("-3") }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Command = $python.Source; Arguments = @() }
    }

    return $null
}

function Ensure-BackendEnvironment {
    $bootstrap = Get-BootstrapPython
    if (-not $bootstrap -and -not (Test-Path $PythonExe)) {
        Write-Host "Python was not found. Install Python 3.11+ to bootstrap the TriCore backend." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }

    if (-not (Test-Path $PythonExe)) {
        Write-Host "Creating backend virtual environment..." -ForegroundColor Yellow
        Push-Location $BackendDir
        & $bootstrap.Command @($bootstrap.Arguments + @("-m", "venv", ".venv"))
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Write-Host "Failed to create backend virtual environment." -ForegroundColor Red
            Read-Host "Press Enter to close"
            exit 1
        }
        Pop-Location
    }

    $needsInstall = $true
    if (Test-Path $PythonExe) {
        & $PythonExe -c "import fastapi, uvicorn, pydantic" *> $null
        if ($LASTEXITCODE -eq 0) {
            $needsInstall = $false
        }
    }

    if ($needsInstall) {
        Write-Host "Installing backend dependencies..." -ForegroundColor Yellow
        Push-Location $BackendDir
        & $PythonExe -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Write-Host "Failed to upgrade pip for the backend environment." -ForegroundColor Red
            Read-Host "Press Enter to close"
            exit 1
        }
        & $PythonExe -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Write-Host "Failed to install backend requirements." -ForegroundColor Red
            Read-Host "Press Enter to close"
            exit 1
        }
        Pop-Location
    }
}

function Ensure-DesktopShortcut {
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($DesktopShortcutPath)
        $Shortcut.TargetPath = "powershell.exe"
        $Shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.Description = "Launch TriCore Scanner desktop app"
        if (Test-Path $IconPath) {
            $Shortcut.IconLocation = "$IconPath,0"
        }
        $Shortcut.Save()
        Write-Host "Desktop shortcut ready: $DesktopShortcutPath" -ForegroundColor Green
    }
    catch {
        Write-Host "Could not create desktop shortcut: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Ensure-BackendEnvironment

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "Frontend dependencies were not found. Installing now..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install --strict-ssl=false --no-audit --no-fund
    Pop-Location
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules\electron"))) {
    Write-Host "Electron desktop shell was not found. Installing now..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install --strict-ssl=false --no-audit --no-fund
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

Ensure-DesktopShortcut

Write-Host "Opening TriCore Scanner desktop app..." -ForegroundColor Green
Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run desktop" `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden

Write-Host "TriCore Scanner desktop app is starting." -ForegroundColor Green
