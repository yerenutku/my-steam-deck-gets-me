"""Updates from GitHub releases, offered and started in the game.

  check  (when the app wakes, i.e. Battle.net starts, so WoW isn't running yet): ask GitHub for the newest release;
         if it is newer, leave an offer in the addon's saved file (WowVoiceUpdate = {...}); the addon shows a dialog.
  install (the player pressed "Update now": the addon saved DB.updateRequest and reloaded): git checkout of the
         release tag, packages, then the addon files, but only if the installer put the addon there (marker file;
         an addon from CurseForge is left to CurseForge). Afterwards the app restarts itself.
Only works in an installed copy (a git clone of the public repo); the developer's own copy never updates itself.

release.json (repo root): {"version": "0.5.0", "compat": 1, "after": "reload|restart_wow|restart_steam", "notes": "…"}
compat goes up only when the app and the addon stop understanding each other (a breaking change).
"""

import json
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = "yerenutku/my-steam-deck-gets-me"
ROOT = Path(__file__).resolve().parent.parent
MARKER = ".installed-by-app"                 # in the addon folder: the installer put it there, so we may update it
KEEP = ["service/names.txt"]                 # files the player edits: kept as they are across updates


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=check).stdout.strip()


def is_installed_copy():
    try:
        return REPO in git("remote", "get-url", "origin")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def local_release():
    try:
        return json.loads((ROOT / "release.json").read_text())
    except (OSError, ValueError):
        return {"version": "0", "compat": 1}


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


def latest_release():
    """The newest GitHub release's release.json, or None (offline, no release, ...)."""
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=8) as r:
            tag = json.load(r)["tag_name"]
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{REPO}/{tag}/release.json", timeout=8) as r:
            info = json.load(r)
        info["tag"] = tag
        return info
    except Exception:
        return None


def addon_dirs():
    return sorted((Path.home() / ".local/share/Steam/steamapps/compatdata").glob(
        "*/pfx/drive_c/Program Files (x86)/World of Warcraft/_*_/Interface/AddOns/WowVoice"))


def addon_compat(d):
    m = re.search(r"^## X-Compat:\s*(\d+)", (d / "WowVoice.toc").read_text(errors="replace"), re.M)
    return int(m.group(1)) if m else 1


def saved_files():
    out = []
    for d in addon_dirs():
        out += d.parents[2].glob("WTF/Account/*/SavedVariables/WowVoice.lua")
    return out


def _lua(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def write_offer(info, log):
    """Leave (or clear, info=None) the offer in the addon's saved file. WoW must not be running: it rewrites that
    file at logout. WoW loads it at the next login, the addon shows the dialog."""
    ours = all((d / MARKER).exists() for d in addon_dirs())
    for f in saved_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"\nWowVoiceUpdate = (?:nil|\{.*?\n\})\n", "\n", text, flags=re.S)
        if info:
            text = text.rstrip("\n") + "\n" + (
                f'WowVoiceUpdate = {{\n["version"] = {_lua(info["version"])},\n["notes"] = {_lua(info.get("notes", ""))},\n'
                f'["addon"] = {"true" if ours else "false"},\n}}\n')
        f.write_text(text, encoding="utf-8")
    if info:
        log(f"update: {info['version']} available (now {local_release()['version']}); offered in the game")


def check(wow_running, log):
    """At wake-up: offer a newer release in the game (only while WoW is closed)."""
    if not is_installed_copy() or wow_running():
        return
    info = latest_release()
    newer = info and vtuple(info["version"]) > vtuple(local_release()["version"])
    write_offer(info if newer else None, log)


def install(version, log, wait_before_addon=10):
    """Install release `version`. Returns its release.json. Raises on failure (nothing half-done in the app: git
    restores the old checkout)."""
    if not is_installed_copy():
        raise RuntimeError("not an installed copy (developer folder): no self-update")
    tag = "v" + version.lstrip("v")
    old = git("rev-parse", "HEAD")
    kept = {k: (ROOT / k).read_bytes() for k in KEEP if (ROOT / k).exists()}
    git("fetch", "-q", "--tags", "origin")
    git("checkout", "-q", "-f", tag)
    try:
        for k, data in kept.items():
            (ROOT / k).write_bytes(data)
        subprocess.run([str(ROOT / "tools/bin/uv"), "pip", "install", "-q", "--python", str(ROOT / "envs/sherpa/bin/python"),
                        "-r", str(ROOT / "envs/requirements-tool.txt")], check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "UV_CACHE_DIR": str(ROOT / ".cache/uv"),
                            "UV_PYTHON_INSTALL_DIR": str(ROOT / "tools/python")})
    except Exception:
        git("checkout", "-q", "-f", old)
        raise
    log(f"update: app is now {version}")
    time.sleep(wait_before_addon)                    # the reload that brought the request must be over first
    for d in addon_dirs():
        if not (d / MARKER).exists():
            log(f"update: addon in {d.parents[2].name} came from elsewhere (CurseForge?): left alone")
            continue
        staging = d.with_name("WowVoice.new")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(ROOT / "addon/WowVoice", staging)
        (staging / MARKER).touch()
        old_dir = d.with_name("WowVoice.old")
        shutil.rmtree(old_dir, ignore_errors=True)
        d.rename(old_dir)
        staging.rename(d)
        shutil.rmtree(old_dir, ignore_errors=True)
        log(f"update: addon in {d.parents[2].name} is now {version}")
    return local_release()


def restart_app(log):
    """The service is named after the install folder (my-steam-deck-gets-me)."""
    log("update: restarting the app")
    subprocess.Popen(["systemctl", "--user", "--no-block", "restart", ROOT.name])
