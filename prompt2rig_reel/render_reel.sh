#!/usr/bin/env bash
# Renders every HQ take side by side with its source clip in Blender, then joins them into one reel.
#   ./render_reel.sh            full quality
#   ./render_reel.sh --preview  quarter res, 8 samples (fast look-dev)
cd "$(dirname "$0")" && source ./config.sh
here=$(pwd); set -e
[ -f "$BLENDER" ] || { echo "Blender not found: edit BLENDER in config.sh"; exit 1; }
cd "$REPO"
shopt -s nullglob; takes=(takes/*_hq.glb)
[ ${#takes[@]} -gt 0 ] || { echo "no takes/*_hq.glb yet: export takes from the app first"; exit 1; }
list=$(mktemp)
for t in "${takes[@]}"; do
  echo "== $t"
  "$BLENDER" -b -P tools/render_blender.py -- "$t" --side-by-side $1
  c="renders/$(basename "${t%.glb}")_compare.mp4"
  [ -f "$c" ] && echo "$c" >> "$list"
done
# Compare clips can differ in width (portrait vs landscape sources): normalize, then concat.
inputs=(); filt=""; i=0
while read -r c; do inputs+=(-i "$c")
  filt+="[$i:v]fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x202020,setsar=1[v$i];"
  i=$((i+1)); done < "$list"
[ $i -gt 0 ] || { echo "no *_compare.mp4 written (needs ffmpeg on PATH and each take's .json)"; exit 1; }
for ((k=0;k<i;k++)); do filt+="[v$k]"; done
ffmpeg -y -loglevel error "${inputs[@]}" -filter_complex "${filt}concat=n=$i:v=1:a=0[out]" -map "[out]" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p "$here/$REEL"
echo "reel: $here/$REEL"
