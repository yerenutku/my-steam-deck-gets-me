#!/usr/bin/env python3
"""Set up the R4 mode shift in Steam's controller layout for the Battle.net shortcut (used by install.sh).

While R4 is held, the right joystick must only steer the chat wheel, or the camera turns as well. Steam's way: a
"mode shift" on R4 that turns the right joystick into a D-pad with no commands. This script adds exactly that:
  - a new D-pad group without commands for the right joystick,
  - R4 = "mode_shift right_joystick <that group>" (whatever R4 did before is replaced),
  - any older mode shift of the right joystick is removed (on any button).
Everything else in the layout stays as it is.

Steam's layout files are plain text (an undocumented format), synced through Steam Cloud. Steam must be CLOSED while
the file is written, or it overwrites it; on its next start it keeps and uploads ours (tested on a Steam Deck OLED,
November 2026). The original is saved first, and `restore` puts it back.

  python3 steam_modeshift.py check          what is there (exit 0 = R4 already set up, 1 = not, 2 = no layout)
  python3 steam_modeshift.py setup          add the mode shift (Steam must be closed)
  python3 steam_modeshift.py restore        put the saved original back (Steam must be closed)
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

STEAM = Path.home() / ".local/share/Steam"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
R4 = "button_back_right_upper"
BACK_BUTTONS = ("button_back_left_upper", "button_back_right_upper", "button_back_left", "button_back_right")


def steam_running():
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0


def layout_files():
    """Steam names a non-Steam game's layout folder after its exe: lowercase, only letters, digits and spaces
    ("Battle.net Launcher.exe" -> "battlenet launcherexe")."""
    names = set()
    for vdf in STEAM.glob("userdata/*/config/shortcuts.vdf"):
        for m in re.finditer(rb"/[^\"\x00/]*?(Battle\.net Launcher\.exe)", vdf.read_bytes()):
            names.add(re.sub(r"[^a-z0-9 ]", "", m.group(1).decode().lower()))
    files = []
    for name in sorted(names):
        files += sorted(STEAM.glob(f"steamapps/common/Steam Controller Configs/*/config/{name}/controller_neptune.vdf"))
    return files


def _input_block(text, start, key):
    """(start, end) of `"key" { ... }` at three tabs, searched from `start` until the group ends."""
    group_end = text.index("\n\t}\n", start)
    i = text.find(f'\t\t\t"{key}"\n', start, group_end)
    if i < 0:
        return None
    return i, text.index("\n\t\t\t}\n", i) + len("\n\t\t\t}\n")


def _switches_group(text):
    """Start of the button group the preset marks as "switch active"."""
    m = re.search(r'"(\d+)"\t\t"switch active"', text)
    if not m:
        return None
    g = re.search(r'\t"group"\n\t\{\n\t\t"id"\t\t"' + m.group(1) + r'"\n\t\t"mode"\t\t"switches"', text)
    return g.start() if g else None


def is_set_up(text):
    sw = _switches_group(text)
    if sw is None:
        return False
    b = _input_block(text, sw, R4)
    m = b and re.search(r'"mode_shift right_joystick (\d+)"', text[b[0]:b[1]])
    if not m:
        return False
    n = m.group(1)
    return bool(re.search(rf'"{n}"\t\t"right_joystick active modeshift"', text))


def add_mode_shift(text):
    sw = _switches_group(text)
    if sw is None:
        raise ValueError("this layout has no button group to change")
    new_id = max(int(i) for i in re.findall(r'\t\t"id"\t\t"(\d+)"', text)) + 1
    # 1. the D-pad without commands, before the preset
    group = ('\t"group"\n\t{\n'
             f'\t\t"id"\t\t"{new_id}"\n\t\t"mode"\t\t"dpad"\n\t\t"name"\t\t""\n\t\t"description"\t\t""\n'
             '\t\t"inputs"\n\t\t{\n\t\t}\n\t\t"settings"\n\t\t{\n\t\t\t"requires_click"\t\t"0"\n\t\t}\n\t}\n')
    p = text.index('\t"preset"\n')
    text = text[:p] + group + text[p:]
    # 2. the preset: the right joystick's mode shift is now that group (older ones are dropped)
    text = re.sub(r'\t\t\t"\d+"\t\t"right_joystick (?:active|inactive) modeshift"\n', "", text)
    gsb = text.index('"group_source_bindings"', text.index('\t"preset"\n'))
    brace = text.index("{\n", gsb) + 2
    text = text[:brace] + f'\t\t\t"{new_id}"\t\t"right_joystick active modeshift"\n' + text[brace:]
    # 3. buttons: no other button shifts the right joystick any more; R4 does, to the new group
    sw = _switches_group(text)
    for key in BACK_BUTTONS:
        b = _input_block(text, sw, key)
        if b and ("mode_shift right_joystick" in text[b[0]:b[1]] or key == R4):
            text = text[:b[0]] + text[b[1]:]
    r4 = (f'\t\t\t"{R4}"\n\t\t\t{{\n\t\t\t\t"activators"\n\t\t\t\t{{\n\t\t\t\t\t"Full_Press"\n\t\t\t\t\t{{\n'
          f'\t\t\t\t\t\t"bindings"\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\t"binding"\t\t"mode_shift right_joystick {new_id}"\n'
          '\t\t\t\t\t\t}\n\t\t\t\t\t\t"settings"\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t"interruptable"\t\t"0"\n\t\t\t\t\t\t}\n'
          '\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t\t"disabled_activators"\n\t\t\t\t{\n\t\t\t\t}\n\t\t\t}\n')
    inputs = text.index('\t\t"inputs"\n\t\t{\n', sw) + len('\t\t"inputs"\n\t\t{\n')
    text = text[:inputs] + r4 + text[inputs:]
    if text.count("{") != text.count("}"):
        raise ValueError("internal error: braces don't match")
    return text


def backup_path(f):
    return BACKUP_DIR / f.parent.name / f.name


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    files = layout_files()
    if not files:
        print("No Steam controller layout for the Battle.net shortcut yet. Open it once in Steam (Controller settings"
              " > Edit layout), change anything and back, then run this again. Or set it up by hand.")
        sys.exit(2)
    if cmd == "check":
        done = all(is_set_up(f.read_text(encoding="utf-8")) for f in files)
        print("R4 mode shift: " + ("set up" if done else "not set up"))
        sys.exit(0 if done else 1)
    if steam_running():
        print("Steam is running. Close it first (Desktop Mode: Steam menu > Exit), then try again.")
        sys.exit(3)
    for f in files:
        if cmd == "setup":
            text = f.read_text(encoding="utf-8")
            if is_set_up(text):
                print(f"already set up: {f}")
                continue
            b = backup_path(f)
            b.parent.mkdir(parents=True, exist_ok=True)
            if not b.exists():                           # keep the very first original
                shutil.copy2(f, b)
            f.write_text(add_mode_shift(text), encoding="utf-8")
            print(f"done: R4 mode shift added to {f}\n  original saved in {b}")
        elif cmd == "restore":
            b = backup_path(f)
            if not b.exists():
                print(f"no saved original for {f}")
                continue
            shutil.copy2(b, f)
            print(f"restored: {f}")
        else:
            print(__doc__)
            sys.exit(2)


if __name__ == "__main__":
    main()
