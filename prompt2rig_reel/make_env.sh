#!/usr/bin/env bash
# Writes $REPO/.env as plain UTF-8 without echoing the key to the screen or shell history.
cd "$(dirname "$0")" && source ./config.sh
read -rsp "fal API key (input hidden): " key; echo
key="${key%\"}"; key="${key#\"}"   # server.mjs does not strip quotes
[ -n "$key" ] || { echo "empty key, nothing written"; exit 1; }
printf 'FAL_KEY=%s\n' "$key" > "$REPO/.env"
echo "wrote $REPO/.env"
