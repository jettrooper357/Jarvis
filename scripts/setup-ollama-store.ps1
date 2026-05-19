<#
  Phase 2 (Windows side): give Ollama a native-ext4 model store without
  touching the nearly-full C: drive.

  Creates an expandable ext4 VHD on F: (where the space is), attaches it to
  WSL2 as a real block device, then hands off to setup-ollama-store.sh which
  formats/mounts it and repoints the WSL ollama service at it.

  WHY: OLLAMA_MODELS currently lives on /mnt/f (a 9p/drvfs Windows mount).
  llama.cpp memory-maps the weights, so every page fault crosses the
  Windows<->WSL bridge and inference is ~50-100x too slow. A VHD attached as
  a block device is native ext4 to WSL while the file still lives on F:.

  Idempotent and safe to call on every launch:
    * already mounted        -> exits immediately
    * not running elevated   -> warns and exits 0 (Phase 1 -nommap path
                                keeps working on the slow mount)
  `wsl --mount` and `diskpart` require Administrator; run the launcher as
  Administrator once to provision this.
#>
[CmdletBinding()]
param(
  [string]$VhdPath    = 'F:\Ollama\ollama-ext4.vhdx',
  [int]   $VhdSizeGB  = 64,
  [string]$MountPoint = '/opt/ollama-store',
  [string]$BaseModel  = 'qwen2.5-coder:7b'
)
$ErrorActionPreference = 'Stop'

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)
}

# --- 0. Fast idempotent path: already mounted in WSL? --------------------
$already = & wsl -u root -e bash -c "mountpoint -q $MountPoint && echo yes || echo no" 2>$null
if ($already -match 'yes') {
  Write-Host "[ollama-store] already mounted at $MountPoint - nothing to do."
  exit 0
}

# --- 1. Needs elevation for diskpart + `wsl --mount` --------------------
if (-not (Test-Admin)) {
  Write-Warning ("[ollama-store] Not elevated -> skipping fast-disk setup. " +
    "Ollama stays on the slow /mnt/f mount with the -nommap workaround " +
    "(Phase 1). To enable the fast ext4 store, run this launcher as " +
    "Administrator once.")
  exit 0
}

# --- 2. Create the expandable ext4 VHD on F: (no Hyper-V needed) --------
if (-not (Test-Path $VhdPath)) {
  Write-Host "[ollama-store] creating VHD $VhdPath ($VhdSizeGB GB, expandable)"
  New-Item -ItemType Directory -Force -Path (Split-Path $VhdPath) | Out-Null
  $script = "create vdisk file=`"$VhdPath`" maximum=$($VhdSizeGB * 1024) type=expandable"
  $tmp = [IO.Path]::GetTempFileName()
  Set-Content -Path $tmp -Value $script -Encoding ascii
  try { & diskpart /s $tmp | Out-Null } finally { Remove-Item $tmp -Force }
  if (-not (Test-Path $VhdPath)) { throw "diskpart did not create $VhdPath" }
}

# --- 3. Attach the VHD into WSL as a bare block device ------------------
# Tolerate "already attached" (exit code != 0) - the .sh detects state.
Write-Host "[ollama-store] attaching $VhdPath to WSL (bare)"
& wsl --mount --vhd "$VhdPath" --bare 2>$null
# (no throw: re-runs after a prior attach are expected to 'fail' here)

# --- 4. Hand off to the Linux side (format/mount/systemd/pull) ----------
# Strip CRLFs so the .sh runs regardless of how it was checked out.
$shWin = Join-Path $PSScriptRoot 'setup-ollama-store.sh'
$shWsl = (& wsl -e wslpath -a "$shWin").Trim()
Write-Host "[ollama-store] running $shWsl as root"
& wsl -u root -e bash -c "tr -d '\r' < '$shWsl' | OLLAMA_BASE_MODEL='$BaseModel' OLLAMA_STORE_MNT='$MountPoint' bash -s"
if ($LASTEXITCODE -ne 0) { throw "setup-ollama-store.sh failed (exit $LASTEXITCODE)" }

Write-Host "[ollama-store] Phase 2 complete - Ollama now on native ext4 ($VhdPath)."
