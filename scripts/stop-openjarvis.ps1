param(
  [switch]$KeepWsl
)

$ErrorActionPreference = 'Continue'

function Stop-ListeningPort {
  param([int]$Port)

  $pids = @()
  try {
    $pids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
  } catch {
    $pids = @()
  }

  foreach ($owningPid in $pids) {
    if (-not $owningPid) { continue }
    try {
      $proc = Get-Process -Id $owningPid -ErrorAction Stop
      Write-Host "[stop] stopping port $Port process $($proc.ProcessName) ($owningPid)"
      Stop-Process -Id $owningPid -Force -ErrorAction Stop
    } catch {
      Write-Warning "[stop] failed to stop PID $owningPid on port ${Port}: $($_.Exception.Message)"
    }
  }
}

function Stop-ProjectJarvisProcesses {
  $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
  $escapedRoot = [regex]::Escape($projectRoot)
  $processes = @()
  try {
    $processes = Get-CimInstance Win32_Process |
      Where-Object {
        ($_.CommandLine -match $escapedRoot) -and
        ($_.CommandLine -match 'jarvis(\.exe)?["\s]+serve|jarvis serve')
      }
  } catch {
    $processes = @()
  }

  foreach ($proc in $processes) {
    try {
      Write-Host "[stop] stopping Jarvis server process $($proc.Name) ($($proc.ProcessId))"
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    } catch {
      Write-Warning "[stop] failed to stop Jarvis PID $($proc.ProcessId): $($_.Exception.Message)"
    }
  }
}

function Invoke-OllamaUnload {
  $base = 'http://127.0.0.1:11434'
  try {
    $running = Invoke-RestMethod -Method Get -Uri "$base/api/ps" -TimeoutSec 3
  } catch {
    Write-Host "[stop] Ollama API not reachable; skipping model unload"
    return
  }

  $models = @($running.models | ForEach-Object { $_.name } | Where-Object { $_ })
  foreach ($model in $models) {
    try {
      Write-Host "[stop] unloading Ollama model $model"
      Invoke-RestMethod `
        -Method Post `
        -Uri "$base/api/generate" `
        -ContentType 'application/json' `
        -Body (@{ model = $model; prompt = ''; keep_alive = 0 } | ConvertTo-Json -Compress) `
        -TimeoutSec 20 | Out-Null
    } catch {
      Write-Warning "[stop] failed to unload ${model}: $($_.Exception.Message)"
    }
  }
}

Write-Host "[stop] stopping OpenJarvis frontend/backend"
Stop-ListeningPort -Port 5173
Stop-ListeningPort -Port 8000
Stop-ProjectJarvisProcesses
Stop-ListeningPort -Port 5173
Stop-ListeningPort -Port 8000

Write-Host "[stop] stopping Jarvis processes inside WSL"
wsl.exe -e bash -lc "ps -eo pid,comm,args | awk '(\$2==\"jarvis\" && index(\$0,\" serve\")) || (\$2==\"uv\" && index(\$0,\"jarvis serve\")) || (\$2==\"sudo\" && index(\$0,\"du -xh\")) {print \$1}' | xargs -r kill 2>/dev/null || true" 2>$null

Invoke-OllamaUnload

Write-Host "[stop] killing any remaining WSL Ollama model runners"
wsl.exe -u root -e bash -lc "ps -eo pid,comm,args | awk '\$2==\"ollama\" && index(\$0,\" runner \") {print \$1}' | xargs -r kill -9 2>/dev/null || true" 2>$null

if (-not $KeepWsl) {
  Write-Host "[stop] shutting down WSL to release vmmemWSL memory"
  wsl.exe --shutdown
} else {
  Write-Host "[stop] KeepWsl set; leaving WSL running"
}

Write-Host "[stop] done"
