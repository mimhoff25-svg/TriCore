param(
    [switch]$Restore
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProbeExe = Join-Path $ProjectRoot "runtime\rtlsdrblog-release\Release\x86\rtl_test.exe"
$DevicePattern = 'VID_0BDA&PID_2838'
$ProcessNames = @('FMP24', 'DSDPlus', 'rtl_test', 'rtl_fm')

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RtlInterfaces {
    Get-PnpDevice -PresentOnly -ErrorAction Stop |
        Where-Object { $_.InstanceId -match $DevicePattern } |
        Sort-Object InstanceId
}

function Set-RtlInterfaceState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstanceId,
        [Parameter(Mandatory = $true)]
        [bool]$Enable
    )

    $verb = if ($Enable) { 'enable' } else { 'disable' }
    try {
        if ($Enable) {
            Enable-PnpDevice -InstanceId $InstanceId -Confirm:$false -ErrorAction Stop | Out-Null
        }
        else {
            Disable-PnpDevice -InstanceId $InstanceId -Confirm:$false -ErrorAction Stop | Out-Null
        }
        return
    }
    catch {
        & pnputil /$verb-device "$InstanceId" | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw
        }
    }
}

function Stop-SdrProcesses {
    Get-Process -Name $ProcessNames -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    $service = Get-Service -Name 'RtlService' -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne 'Stopped') {
        try {
            Stop-Service -Name 'RtlService' -Force -ErrorAction Stop
            Write-Host 'Stopped RtlService.' -ForegroundColor Yellow
        }
        catch {
            Write-Host "Could not stop RtlService: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

if (-not (Test-Administrator)) {
    Write-Host 'Run this script from an elevated PowerShell window.' -ForegroundColor Red
    exit 1
}

try {
    $interfaces = Get-RtlInterfaces
}
catch {
    Write-Host "Could not query RTL-SDR interfaces: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if (-not $interfaces) {
    Write-Host 'No RTL2838 interfaces were found.' -ForegroundColor Red
    exit 1
}

Write-Host 'Current RTL interfaces:' -ForegroundColor Cyan
$interfaces |
    Select-Object FriendlyName, InstanceId, Status, Service |
    Format-Table -AutoSize |
    Out-Host

$extraInterface = $interfaces | Where-Object { $_.InstanceId -match 'MI_01' } | Select-Object -First 1

if ($Restore) {
    if (-not $extraInterface) {
        Write-Host 'No MI_01 interface is present to restore.' -ForegroundColor Yellow
        exit 0
    }

    try {
        Set-RtlInterfaceState -InstanceId $extraInterface.InstanceId -Enable $true
        Write-Host "Re-enabled $($extraInterface.InstanceId)." -ForegroundColor Green
    }
    catch {
        Write-Host "Failed to re-enable $($extraInterface.InstanceId): $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }

    exit 0
}

Stop-SdrProcesses

if ($extraInterface) {
    try {
        Set-RtlInterfaceState -InstanceId $extraInterface.InstanceId -Enable $false
        Write-Host "Disabled extra RTL interface $($extraInterface.InstanceId)." -ForegroundColor Green
    }
    catch {
        Write-Host "Failed to disable $($extraInterface.InstanceId): $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}
else {
    Write-Host 'No MI_01 interface was found. Nothing to disable.' -ForegroundColor Yellow
}

try {
    $afterInterfaces = Get-RtlInterfaces
    Write-Host 'RTL interfaces after change:' -ForegroundColor Cyan
    $afterInterfaces |
        Select-Object FriendlyName, InstanceId, Status, Service |
        Format-Table -AutoSize |
        Out-Host
}
catch {
    Write-Host "Could not refresh interface state: $($_.Exception.Message)" -ForegroundColor Yellow
}

if (Test-Path $ProbeExe) {
    Write-Host 'Running 32-bit rtl_test probe:' -ForegroundColor Cyan
    & $ProbeExe -t
    Write-Host "rtl_test exit code: $LASTEXITCODE" -ForegroundColor Cyan
}
else {
    Write-Host "Probe executable not found at $ProbeExe" -ForegroundColor Yellow
}

Write-Host 'Restart TriCore and retry P25 after the probe completes.' -ForegroundColor Green