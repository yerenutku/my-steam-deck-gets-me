#!/bin/bash
# My Steam Deck Gets Me: installer. In Desktop Mode, in Konsole:
#   git clone https://github.com/yerenutku/my-steam-deck-gets-me.git ~/my-steam-deck-gets-me && bash ~/my-steam-deck-gets-me/install.sh
# Safe to run again (it skips what is already there). Everything stays in ~/my-steam-deck-gets-me; no root password needed.
# Options: --no-addon (don't copy the WoW addon), --no-service (don't set up the autostart).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON=1; SERVICE=1
for a in "$@"; do
  case "$a" in
    --no-addon) ADDON=0 ;;
    --no-service) SERVICE=0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }

if [ "$SERVICE" = 1 ] && [ "$DIR" != "$HOME/my-steam-deck-gets-me" ]; then
  echo "Please put this folder at ~/my-steam-deck-gets-me (the autostart expects it there): it is at $DIR"
  exit 1
fi

step "1/5 Checking the system"
for tool in pw-record pactl pgrep curl; do
  command -v "$tool" >/dev/null && ok "$tool" || { warn "$tool is missing (SteamOS has it; other systems: install it)"; exit 1; }
done
command -v xdotool >/dev/null && ok "xdotool (Desktop Mode window check)" || warn "xdotool missing: in Desktop Mode the tool can't see which window is in front"
[ -w /dev/uinput ] && ok "/dev/uinput (typing into WoW)" || warn "/dev/uinput is not writable: the tool can't type (SteamOS allows it for the deck user)"

step "2/5 Python and packages"
mkdir -p "$DIR/tools/bin"
if [ ! -x "$DIR/tools/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$DIR/tools/bin" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
fi
ok "uv $("$DIR/tools/bin/uv" --version | cut -d' ' -f2)"
# shellcheck source=env.sh
source "$DIR/env.sh"
[ -x "$DIR/envs/sherpa/bin/python" ] || uv venv -q --python 3.12 "$DIR/envs/sherpa"
uv pip install -q --python "$DIR/envs/sherpa/bin/python" -r "$DIR/envs/requirements-tool.txt"
"$DIR/envs/sherpa/bin/python" -c "import transcribe_cpp, sherpa_onnx, soxr, soundfile, numpy" && ok "packages"

step "3/5 Speech model (about 1.2 GB) and pause detector"
fetch() {   # url target min_bytes
  if [ -f "$2" ] && [ "$(stat -c %s "$2")" -ge "$3" ]; then ok "$(basename "$2") (already there)"; return; fi
  mkdir -p "$(dirname "$2")"
  curl -L --fail --progress-bar -o "$2.part" "$1" && mv "$2.part" "$2"
  [ "$(stat -c %s "$2")" -ge "$3" ] && ok "$(basename "$2")" || { warn "$(basename "$2") looks incomplete"; exit 1; }
}
fetch https://huggingface.co/handy-computer/parakeet-unified-en-0.6b-gguf/resolve/main/parakeet-unified-en-0.6b-F16.gguf \
  "$DIR/models/gguf/handy-computer--parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-F16.gguf" 1000000000
fetch https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx \
  "$DIR/models/silero_vad.onnx" 500000

step "4/5 The WoW addon"
if [ "$ADDON" = 0 ]; then
  ok "skipped (--no-addon)"
else
  found=0
  for wow in "$HOME"/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/"Program Files (x86)"/"World of Warcraft"/_*_; do
    [ -d "$wow" ] || continue
    mkdir -p "$wow/Interface/AddOns"
    rm -rf "$wow/Interface/AddOns/WowVoice"
    cp -r "$DIR/addon/WowVoice" "$wow/Interface/AddOns/"
    ok "copied to $(basename "$wow") ($wow)"
    found=1
  done
  [ "$found" = 1 ] || warn "WoW not found in Steam's Proton folders. Install WoW first (Battle.net as a non-Steam game), then run this again."
fi

step "5/5 Autostart"
if [ "$SERVICE" = 0 ]; then
  ok "skipped (--no-service)"
else
  mkdir -p "$HOME/.config/systemd/user" "$DIR/.cache"
  cp "$DIR/service/my-steam-deck-gets-me.service" "$HOME/.config/systemd/user/my-steam-deck-gets-me.service"
  systemctl --user daemon-reload
  systemctl --user enable -q my-steam-deck-gets-me
  systemctl --user restart my-steam-deck-gets-me
  sleep 1
  systemctl --user is-active -q my-steam-deck-gets-me && ok "running; it sleeps until you start Battle.net or WoW" \
    || { warn "the service didn't start: systemctl --user status my-steam-deck-gets-me"; exit 1; }
fi

cat <<'EOF'

Done. Two things left, both one time only:

 1. In WoW: Options > Social > Chat Style: Classic.
 2. In Steam (so the right stick doesn't turn the camera while the wheel is open):
    your WoW / Battle.net entry > Controller settings > Edit layout
      - Back grip buttons: remove any command from R4
      - Right joystick > settings > Mode shift: button R4, mode "Directional Pad", leave its directions empty

Then start Battle.net and WoW, hold R4, speak, let go. You'll see "Voice ready" shortly after logging in.
Uninstall: bash ~/my-steam-deck-gets-me/uninstall.sh
EOF
