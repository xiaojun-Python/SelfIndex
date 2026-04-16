param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",

    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DataDir = Join-Path $ProjectRoot "data"
$PidFile = Join-Path $DataDir "selfindex-service.pid"
$StdOutLogFile = Join-Path $DataDir "selfindex-service.out.log"
$StdErrLogFile = Join-Path $DataDir "selfindex-service.err.log"

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

function Get-RunningProcessByPidFile {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $rawPid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $rawPid) {
        return $null
    }

    try {
        $pidValue = [int]$rawPid
    } catch {
        return $null
    }

    return Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

function Get-ListeningPidsByPort {
    $lines = cmd /c "netstat -ano -p TCP" 2>$null
    if (-not $lines) {
        return @()
    }

    $pattern = "^\s*TCP\s+(\S+):$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $results = @()
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            $results += [int]$Matches[2]
        }
    }
    return $results | Sort-Object -Unique
}

function Remove-StalePidFile {
    if (Test-Path $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
}

function Stop-SelfIndexProcess {
    $stopped = $false

    $process = Get-RunningProcessByPidFile
    if ($process) {
        Write-Host "Stopping SelfIndex PID $($process.Id)..."
        Stop-Process -Id $process.Id -Force
        $stopped = $true
    }

    Remove-StalePidFile

    $listeningPids = Get-ListeningPidsByPort
    foreach ($listeningPid in $listeningPids) {
        if ($process -and $listeningPid -eq $process.Id) {
            continue
        }
        $listeningProcess = Get-Process -Id $listeningPid -ErrorAction SilentlyContinue
        if ($null -eq $listeningProcess) {
            continue
        }

        $processPath = ""
        try {
            $processPath = $listeningProcess.Path
        } catch {
            $processPath = ""
        }

        if ($processPath -and ($processPath -like "$ProjectRoot*")) {
            Write-Host "Stopping project-local listener PID $listeningPid..."
            Stop-Process -Id $listeningPid -Force
            $stopped = $true
            continue
        }

        if ($processPath -and ($processPath -like "*python.exe")) {
            Write-Host "Port $Port is occupied by Python PID $listeningPid. Stopping it..."
            Stop-Process -Id $listeningPid -Force
            $stopped = $true
        }
    }

    if (-not $stopped) {
        Write-Host "No managed SelfIndex service was running."
    }
}

function Start-SelfIndexProcess {
    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found: $PythonExe"
    }

    $current = Get-RunningProcessByPidFile
    if ($current) {
        Write-Host "SelfIndex already running on PID $($current.Id)."
        return
    }

    $portListeners = Get-ListeningPidsByPort
    if ($portListeners.Count -gt 0) {
        Write-Host "Port $Port already has listener(s): $($portListeners -join ', '). Stopping them first..."
        Stop-SelfIndexProcess
        Start-Sleep -Milliseconds 700
    }

    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $env:HOST = $HostAddress
    $env:PORT = [string]$Port

    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "-m app.main" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $StdOutLogFile `
        -RedirectStandardError $StdErrLogFile

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii

    Write-Host "SelfIndex started on PID $($process.Id)."
    Write-Host "Web: http://$HostAddress`:$Port/"
    Write-Host "Ingest: http://$HostAddress`:$Port/api/ingest/chatgpt-browser"
    Write-Host "Stdout log: $StdOutLogFile"
    Write-Host "Stderr log: $StdErrLogFile"
}

function Show-Status {
    $process = Get-RunningProcessByPidFile
    $listeners = Get-ListeningPidsByPort

    if ($process) {
        Write-Host "Managed SelfIndex is running."
        Write-Host "PID: $($process.Id)"
    } else {
        Write-Host "Managed SelfIndex is not running."
    }

    if ($listeners.Count -gt 0) {
        Write-Host "Port $Port listeners: $($listeners -join ', ')"
    } else {
        Write-Host "Port $Port has no listeners."
    }

    Write-Host "Expected web URL: http://$HostAddress`:$Port/"
    Write-Host "Expected ingest URL: http://$HostAddress`:$Port/api/ingest/chatgpt-browser"
    if (Test-Path $StdOutLogFile) {
        Write-Host "Stdout log: $StdOutLogFile"
    }
    if (Test-Path $StdErrLogFile) {
        Write-Host "Stderr log: $StdErrLogFile"
    }
}

switch ($Action) {
    "start" { Start-SelfIndexProcess }
    "stop" { Stop-SelfIndexProcess }
    "restart" {
        Stop-SelfIndexProcess
        Start-Sleep -Milliseconds 700
        Start-SelfIndexProcess
    }
    "status" { Show-Status }
}
