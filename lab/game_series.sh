#!/bin/bash
# Runs a series of while-gaming tests back to back (WowVoiceFPS addon records WoW's frames).
# Usage: lab/game_series.sh uncapped|capped30
# Gives 20 s to switch to WoW first (WoW must be in the FOREGROUND: in the background it caps its FPS).
cd "$HOME/wowvoice" || exit 1
tag="${1:-uncapped}"
notify-send -a "wowvoice test" -t 15000 "Switch to WoW now - tests start in 20 s (stand still)"
sleep 20
common=(--rounds 5 --baseline 15 --gap 6)
envs/nemo/bin/python   lab/game_test.py --engine nemo "${common[@]}" --label "nemo-big-$tag"
envs/sherpa/bin/python lab/game_test.py --engine qwen "${common[@]}" --label "qwen-big-$tag"
envs/sherpa/bin/python lab/game_test.py --engine qwen "${common[@]}" --names lab/names.txt --label "qwen-small-$tag"
notify-send -a "wowvoice test" -t 10000 "Tests done ($tag)"
