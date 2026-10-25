#!/usr/bin/env bash
# One-time HQ setup from Git Bash.
#   ./setup_hq.sh                    venv, CUDA PyTorch, GVHMR + ~5 GB checkpoints (runs hq/setup.ps1)
#   ./setup_hq.sh --hands <mano.zip> optional finger tracking (WiLoR + MANO)
cd "$(dirname "$0")" && source ./config.sh
set -e
HQ="$REPO/hq"
if [ "$1" = --hands ]; then
  [ -f "$2" ] || { echo "usage: ./setup_hq.sh --hands ~/Downloads/mano_v1_2.zip"; exit 1; }
  "$HQ/.venv/Scripts/python" "$HQ/setup_hands.py" "$2"
  exit
fi
for t in uv ffmpeg git; do command -v $t >/dev/null || { echo "$t not on PATH (see ./doctor.sh)"; exit 1; }; done
ps1="$HQ/setup.ps1"
if [ "$CUDA_INDEX" != cu126 ]; then  # patched copy next to the original so $PSScriptRoot stays hq/
  sed "s#/whl/cu126#/whl/$CUDA_INDEX#" "$HQ/setup.ps1" > "$HQ/setup_$CUDA_INDEX.ps1"
  ps1="$HQ/setup_$CUDA_INDEX.ps1"
fi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$ps1")"
# setup.ps1 keeps going after a failed native command, so verify the result here.
"$HQ/.venv/Scripts/python" -c "import torch, gvhmr, ultralytics, fastapi; assert torch.cuda.is_available(), 'torch has no CUDA'; print('HQ env OK:', torch.__version__, torch.cuda.get_device_name(0))"
echo "Next: put SMPLX_NEUTRAL.npz in $HQ/body_models/smplx/ then ./run.sh"
