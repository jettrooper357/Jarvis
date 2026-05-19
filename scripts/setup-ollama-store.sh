#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Phase 2 (Linux side): put the Ollama model store on a native ext4 volume.
#
# Invoked as root from setup-ollama-store.ps1 AFTER the F: VHD has been
# attached to WSL as a bare block device (`wsl --mount --vhd ... --bare`).
#
# Why: with OLLAMA_MODELS on /mnt/f (a 9p/drvfs Windows mount), llama.cpp's
# memory-mapped weight reads cross the Windows<->WSL bridge per page fault and
# inference is ~50-100x too slow. A VHD attached as a real block device gives
# native ext4 speed while the backing file still lives on roomy F:.
#
# Idempotent: safe to run on every launch. Re-formats only an unformatted
# disk; never touches an existing OLLAMA-labelled filesystem.
# ---------------------------------------------------------------------------
set -euo pipefail

LABEL="${OLLAMA_STORE_LABEL:-OLLAMA}"
MNT="${OLLAMA_STORE_MNT:-/opt/ollama-store}"
MODEL="${OLLAMA_BASE_MODEL:-qwen2.5-coder:7b}"

log() { echo "[ollama-store] $*"; }

# Already mounted? Nothing to do (fast idempotent path).
if mountpoint -q "$MNT"; then
  log "already mounted at $MNT"
else
  # Prefer an existing OLLAMA-labelled fs (VHD was formatted on a prior run).
  dev=""
  if blkid -L "$LABEL" >/dev/null 2>&1; then
    dev="$(blkid -L "$LABEL")"
    log "found existing $LABEL filesystem at $dev"
  else
    # First run: the freshly --bare-attached VHD is the only whole disk with
    # no filesystem and no partitions. Pick it deterministically.
    while read -r name type fstype; do
      [ "$type" = "disk" ] || continue
      [ -z "$fstype" ] || continue
      if [ -z "$(lsblk -no FSTYPE "$name" | tr -d '[:space:]')" ]; then
        dev="$name"
      fi
    done < <(lsblk -dpno NAME,TYPE,FSTYPE)
    [ -n "$dev" ] || { log "ERROR: no unformatted disk found (was the VHD attached with 'wsl --mount --vhd --bare'?)"; exit 1; }
    log "formatting $dev as ext4 (label=$LABEL)"
    mkfs.ext4 -q -L "$LABEL" "$dev"
  fi
  mkdir -p "$MNT"
  mount -L "$LABEL" "$MNT"
  log "mounted $dev at $MNT"
fi

mkdir -p "$MNT/models"

# Let the ollama service user own the store.
ouser="ollama"
id -u "$ouser" >/dev/null 2>&1 || ouser="root"
chown -R "$ouser":"$ouser" "$MNT" 2>/dev/null || chmod -R 0777 "$MNT"

# Repoint OLLAMA_MODELS at the ext4 store via the systemd drop-in (the
# canonical place this project configures the WSL ollama service).
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment=OLLAMA_MODELS=$MNT/models
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_KEEP_ALIVE=-1
Environment=OLLAMA_NUM_PARALLEL=1
EOF
systemctl daemon-reload
systemctl restart ollama

# Wait for the API on the (initially empty) ext4 store. Use the HTTP API,
# not the `ollama` CLI: the WSL systemd *user* session is broken and
# corrupts the CLI when invoked via `wsl bash`.
API="http://127.0.0.1:11434"
for _ in $(seq 1 60); do
  curl -sf "$API/api/tags" >/dev/null 2>&1 && break
  sleep 1
done

# Ensure the base model exists in the new store (one-time download to fast
# ext4). No "-nommap" variant: mmap is fast on native ext4, and the engine
# already sends use_mmap=false; `ollama create` also can't run on /mnt/f.
if ! curl -sf "$API/api/tags" | grep -qF "$MODEL"; then
  log "pulling $MODEL into the ext4 store (one-time download)"
  curl -sS -X POST "$API/api/pull" -d "{\"model\":\"$MODEL\"}" | tail -n 1
fi

log "ready: OLLAMA_MODELS=$MNT/models  (model: $MODEL)"
