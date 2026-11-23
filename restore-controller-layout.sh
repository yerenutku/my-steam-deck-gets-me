#!/bin/bash
# My Steam Deck Gets Me: put back the Steam controller layout you had before the installer added the R4 mode shift.
# Steam must be closed. Only works if the installer changed your layout (it saved the original in backups/).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! ls "$DIR"/backups/*/controller_neptune.vdf >/dev/null 2>&1; then
  echo "Nothing to restore: the installer never changed your Steam controller layout (no saved original in $DIR/backups)."
  exit 1
fi
while pgrep -x steam >/dev/null; do
  if [ ! -t 0 ]; then echo "Steam is running. Close it first (Steam menu > Exit), then run this again."; exit 1; fi
  read -r -p "Steam is running. Close it (Steam menu > Exit), then press Enter. " _
done
python3 "$DIR/service/steam_modeshift.py" restore && echo "Done. Start Steam again."
