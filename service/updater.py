"""Updates from GitHub releases, installed by the app itself while WoW is closed (no button, nothing to press).

  When the app wakes (Battle.net starts) and when Wow.exe starts (before WoW loads its addons): ask GitHub for the
  newest release; if it is newer: git checkout of the release tag, packages, then the addon files, but only if the
  installer put the addon there (marker file; an addon from CurseForge is left to CurseForge). Then the app restarts
  itself. In the game the addon writes "updated to vX" (and "restart WoW / Steam" when the release needs it).
  (v0.5.0-0.5.11 had an in-game "Update now" button: WoW blocked its popups and reload. Removed.)
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
ADDON, OLD_ADDON = "MySteamDeckGetsMe", "WowVoice"   # the addon folder; its name until v0.5.15
KEEP = []                                    # files the player edits: kept as they are across updates


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


def wow_roots():
    """WoW's game folders (_forever_, _retail_, ...) in Steam's Proton prefixes."""
    return sorted(r for r in (Path.home() / ".local/share/Steam/steamapps/compatdata").glob(
        "*/pfx/drive_c/Program Files (x86)/World of Warcraft/_*_") if (r / "Interface/AddOns").is_dir())


def addon_dirs():
    """The installed addon folders (the old name too, until the next update moves it)."""
    out = []
    for r in wow_roots():
        for name in (ADDON, OLD_ADDON):
            d = r / "Interface/AddOns" / name
            if (d / f"{name}.toc").exists():
                out.append(d)
                break
    return out


def addon_compat(d):
    m = re.search(r"^## X-Compat:\s*(\d+)", (d / f"{d.name}.toc").read_text(errors="replace"), re.M)
    return int(m.group(1)) if m else 1


def saved_files():
    out = []
    for d in addon_dirs():
        out += d.parents[2].glob(f"WTF/Account/*/SavedVariables/{ADDON}.lua")
    return out


def note_misfit(log):
    """If the addon's compat number differs from the app's, leave the addon a note in its save file (WoW hasn't loaded
    it yet): it says at login which side to update."""
    mine = local_release().get("compat", 1)
    theirs = [addon_compat(d) for d in addon_dirs()]
    note = "app_older" if theirs and max(theirs) > mine else "addon_older" if any(c != mine for c in theirs) else None
    for f in saved_files():
        old = f.read_text(encoding="utf-8", errors="surrogateescape")
        text = re.sub(r'\n\["misfit"\] = "[a-z_]+",', "", old)
        if note:
            text = re.sub(r"^(WowVoiceDB = \{)", rf'\1\n["misfit"] = "{note}",', text, count=1, flags=re.M)
        if text != old:                               # leave the player's save file alone when nothing changes
            f.write_text(text, encoding="utf-8", errors="surrogateescape")
    if note:
        log(f"addon (compat {theirs}) and app (compat {mine}) don't fit: noted for the addon ({note})")


def auto_update(wow_running, log, wow_just_started=False):
    """Install a newer release now, if WoW hasn't loaded its addons yet. Returns True if the app was updated (it
    restarts itself then)."""
    if not is_installed_copy() or (wow_running() and not wow_just_started):
        return False
    try:
        note_misfit(log)
    except Exception as e:
        log(f"compat note failed: {e}")
    info = latest_release()
    if not info or vtuple(info["version"]) <= vtuple(local_release()["version"]):
        return False
    log(f"update: {local_release()['version']} -> {info['version']}")
    try:
        install(info["version"], log, wait_before_addon=0)
    except Exception:
        import traceback
        log("update FAILED (nothing changed; next try at the next start):\n" + traceback.format_exc())
        return False
    restart_app(log)
    return True


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
        install_addon(d.parents[2], log)
        log(f"update: addon in {d.parents[2].name} is now {version}")
    return local_release()


def install_addon(root, log):
    """Put the addon into WoW folder `root` (swap in one rename) and move the old name's folder and saved file."""
    addons = root / "Interface/AddOns"
    target, staging, old_dir = addons / ADDON, addons / f"{ADDON}.new", addons / f"{ADDON}.old"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(ROOT / "addon" / ADDON, staging)
    (staging / MARKER).touch()
    shutil.rmtree(old_dir, ignore_errors=True)
    if target.exists():
        target.rename(old_dir)
    staging.rename(target)
    shutil.rmtree(old_dir, ignore_errors=True)
    previous = addons / OLD_ADDON
    if (previous / MARKER).exists():                   # ours under the old name: gone, its data moves along
        shutil.rmtree(previous, ignore_errors=True)
        for sv in root.glob(f"WTF/Account/*/SavedVariables/{OLD_ADDON}.lua"):
            new = sv.with_name(f"{ADDON}.lua")
            if not new.exists():
                shutil.copy2(sv, new)
                log(f"update: saved data moved to the new addon name ({sv.parent.parent.name})")


def restart_app(log):
    """The service is named after the install folder (my-steam-deck-gets-me)."""
    log("update: restarting the app")
    subprocess.Popen(["systemctl", "--user", "--no-block", "restart", ROOT.name])
