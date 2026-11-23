#!/bin/bash
# My Steam Deck Gets Me: uninstaller. Stops the autostart and removes the addon. Your ~/my-steam-deck-gets-me folder (with your
# names list and dictation history) is only deleted when you confirm.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
systemctl --user disable --now my-steam-deck-gets-me 2>/dev/null
rm -f "$HOME/.config/systemd/user/my-steam-deck-gets-me.service"
systemctl --user daemon-reload
echo "autostart removed"
for wow in "$HOME"/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/"Program Files (x86)"/"World of Warcraft"/_*_; do
  [ -d "$wow/Interface/AddOns/WowVoice" ] && rm -rf "$wow/Interface/AddOns/WowVoice" && echo "addon removed from $(basename "$wow")"
done
if [ -d "$DIR/backups" ] && [ -t 0 ]; then
  read -r -p "Put your original Steam controller layout back? Steam must be closed. [y/N] " answer
  if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
    while pgrep -x steam >/dev/null; do read -r -p "Close Steam (Steam menu > Exit), then press Enter. " _; done
    "$DIR/envs/sherpa/bin/python" "$DIR/service/steam_modeshift.py" restore
  fi
fi
read -r -p "Also delete $DIR (models, settings, your dictation history)? [y/N] " answer
if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
  rm -rf "$DIR" && echo "deleted $DIR"
else
  echo "kept $DIR"
fi
