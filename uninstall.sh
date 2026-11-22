#!/bin/bash
# My Steam Deck Gets Me: uninstaller. Stops the autostart and removes the addon. Your ~/wowvoice folder (with your
# names list and dictation history) is only deleted when you confirm.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
systemctl --user disable --now wowvoice 2>/dev/null
rm -f "$HOME/.config/systemd/user/wowvoice.service"
systemctl --user daemon-reload
echo "autostart removed"
for wow in "$HOME"/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/"Program Files (x86)"/"World of Warcraft"/_*_; do
  [ -d "$wow/Interface/AddOns/WowVoice" ] && rm -rf "$wow/Interface/AddOns/WowVoice" && echo "addon removed from $(basename "$wow")"
done
read -r -p "Also delete $DIR (models, settings, your dictation history)? [y/N] " answer
if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
  rm -rf "$DIR" && echo "deleted $DIR"
else
  echo "kept $DIR"
fi
