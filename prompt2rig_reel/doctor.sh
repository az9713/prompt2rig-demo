#!/usr/bin/env bash
# Checks everything the reel needs and says what is missing. Safe to run any time.
cd "$(dirname "$0")" && source ./config.sh
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[31mmissing\033[0m %s\n' "$*"; }
warn() { printf '  \033[33mnote\033[0m  %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "Tier 0 (browser preview)"
have node && ok "node $(node -v)" || bad "node: winget install OpenJS.NodeJS.LTS"
[ -f "$REPO/server.mjs" ] && ok "repo at $REPO" || bad "repo not found at $REPO (edit REPO in config.sh)"
if [ -f "$REPO/.env" ]; then
  # UTF-16 .env (PowerShell 5.1 '>' redirect) is invisible to server.mjs
  if head -c2 "$REPO/.env" | od -An -tx1 | grep -qE 'ff fe|fe ff'; then bad ".env is UTF-16: recreate it with ./make_env.sh"
  elif grep -qE '^\s*FAL_KEY\s*=\s*["'"'"']' "$REPO/.env"; then bad ".env FAL_KEY is quoted: remove the quotes"
  elif grep -qE '^\s*FAL_KEY\s*=\s*\S' "$REPO/.env"; then ok ".env has FAL_KEY"
  else bad ".env has no FAL_KEY line: run ./make_env.sh"; fi
else bad ".env: run ./make_env.sh"; fi

echo "Tier 1 (HQ pass)"
if have nvidia-smi; then
  gpu=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)
  ok "GPU: $gpu"
  if echo "$gpu" | grep -qE 'RTX (PRO )?50[0-9]{2}|RTX 5[0-9]{3}|Blackwell'; then
    [ "$CUDA_INDEX" = cu128 ] && ok "CUDA_INDEX=cu128 (needed for RTX 50)" || bad "RTX 50-series: set CUDA_INDEX=\"cu128\" in config.sh before ./setup_hq.sh"
  fi
else bad "nvidia-smi (no NVIDIA GPU/driver: HQ pass will not run, Tier 0 still works)"; fi
have uv && ok "uv $(uv --version | cut -d' ' -f2)" || bad "uv: winget install astral-sh.uv"
have ffmpeg && ok "ffmpeg" || bad "ffmpeg: winget install Gyan.FFmpeg (new terminal after)"
have git && ok "git" || bad "git"
[ -x "$REPO/hq/.venv/Scripts/python" ] || [ -f "$REPO/hq/.venv/Scripts/python.exe" ] && ok "hq venv" || bad "hq venv: run ./setup_hq.sh"
[ -f "$REPO/hq/body_models/smplx/SMPLX_NEUTRAL.npz" ] && ok "SMPLX_NEUTRAL.npz" || bad "SMPLX_NEUTRAL.npz in $REPO/hq/body_models/smplx/ (smpl-x.is.tue.mpg.de, v1.1 NPZ)"
[ -f "$REPO/hq/weights/wilor/pretrained_models/MANO_RIGHT.pkl" ] && ok "WiLoR + MANO (fingers)" || warn "no MANO: fingers use MediaPipe fallback (optional: ./setup_hq.sh --hands ~/Downloads/mano_v1_2.zip)"
reg=$(reg query 'HKLM\SYSTEM\CurrentControlSet\Control\FileSystem' //v LongPathsEnabled 2>/dev/null | grep -o '0x[01]')
[ "$reg" = 0x1 ] && ok "Windows long paths enabled" || warn "long paths off: if uv fails with path errors, move the repo to C:/p2r or enable LongPathsEnabled"

echo "Tier 2 (Blender reel)"
[ -f "$BLENDER" ] && ok "Blender: $BLENDER" || bad "Blender not at \"$BLENDER\" (edit BLENDER in config.sh; ls '/c/Program Files/Blender Foundation/')"
n=$(ls "$REPO"/takes/*_hq.glb 2>/dev/null | wc -l)
[ "$n" -gt 0 ] && ok "$n HQ take(s) in takes/" || warn "no *_hq.glb takes yet (press ↓ glb in the app after HQ finishes)"
