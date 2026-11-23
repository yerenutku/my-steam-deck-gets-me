#!/usr/bin/env python3
"""Runs the dictation tool (wowvoice.py) only while Battle.net or WoW runs.

While neither runs, nothing is loaded: no microphone, no speech model, no CPU. The sleeper waits in the kernel:
  wake   Linux's inotify reports that the Battle.net launcher, Battle.net.exe or Wow.exe was OPENED (Proton opens
         the .exe to start it). The sleeper then checks that one of them really runs (Battle.net also opens Wow.exe
         to update or scan it) and starts the tool; the model is loaded long before you're in the game.
  sleep  pidfds report when those processes exit. When none is left for GRACE seconds (Battle.net restarts itself
         during updates; its launcher exits after starting Battle.net.exe), the tool is stopped: the microphone and
         the model's memory are freed.
The systemd user service (my-steam-deck-gets-me.service) starts this file; arguments are passed on to wowvoice.py.
Log: ~/my-steam-deck-gets-me/.cache/service.log, lines marked "sleeper:".
"""

import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from inotify import IN_OPEN, Inotify

HERE = Path(__file__).resolve().parent
STEAM = Path.home() / ".local/share/Steam"
EXES = (b"battle.net launcher.exe", b"battle.net.exe", b"wow.exe")
GRACE = 20                  # seconds without Battle.net/WoW before the tool is stopped
CONFIRM = 10                # seconds an opened .exe may take to show up as a running process
POLL = 10                   # fallback only: no folder to watch was found


def log(msg):
    print(time.strftime("%H:%M:%S"), "sleeper:", msg, flush=True)


def watch_folders():
    """The folders holding the Battle.net launcher (from Steam's shortcuts, or the usual place in a Proton prefix)
    and WoW's game folders (_forever_, _retail_, ...)."""
    folders = set()
    for vdf in STEAM.glob("userdata/*/config/shortcuts.vdf"):
        for m in re.finditer(rb'(/[^"\x00]*?Battle\.net Launcher\.exe)', vdf.read_bytes()):
            folders.add(Path(m.group(1).decode(errors="replace")).parent)
    for drive_c in STEAM.glob("steamapps/compatdata/*/pfx/drive_c"):
        folders.add(drive_c / "Program Files (x86)/Battle.net")
        folders.update(drive_c.glob("Program Files (x86)/World of Warcraft/_*_"))
    return sorted(f for f in folders if f.is_dir())


def running():
    """PIDs of Battle.net / WoW processes (Wine shows the Windows path in the command line)."""
    pids = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").lower()
        except OSError:
            continue
        if any(e in cmd for e in EXES) and not cmd.startswith((b"pgrep", b"grep")):
            pids.append(int(p.name))
    return pids


def wait_for_start():
    folders = watch_folders()
    ino = Inotify()
    try:
        for f in folders:
            ino.watch(f, IN_OPEN)
        log("asleep; waiting for Battle.net or WoW (" + (", ".join(map(str, folders)) or f"no folders found: "
                                                          f"checking every {POLL} s") + ")")
        while True:
            if running():                               # (also covers a start between the scan and the watch)
                return
            for _folder, name, _mask in ino.read(None if folders else POLL):
                if name.lower().encode() not in EXES:
                    continue
                deadline = time.monotonic() + CONFIRM
                while time.monotonic() < deadline:
                    if running():
                        log(f"woke: {name} was opened")
                        return
                    time.sleep(0.5)
                log(f"{name} was opened, but nothing runs: back to sleep")
                break
    finally:
        ino.close()


def wait_until_gone(child):
    """Returns "gone" when Battle.net and WoW have been closed for GRACE s, "child" when the tool itself exited."""
    child_fd = os.pidfd_open(child.pid)
    try:
        while True:
            pids = running()
            if not pids:
                if select.select([child_fd], [], [], GRACE)[0]:
                    return "child"
                if not running():
                    return "gone"
                continue
            fds = []
            for pid in pids:
                try:
                    fds.append(os.pidfd_open(pid))
                except OSError:                         # already gone
                    pass
            try:
                ready = select.select(fds + [child_fd], [], [])[0]     # sleeps until one of them exits
            finally:
                for fd in fds:
                    os.close(fd)
            if child_fd in ready:
                return "child"
    finally:
        os.close(child_fd)


def stop(child):
    child.terminate()                                   # the tool restores the game sound and closes the mic
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    child = None
    try:
        while True:
            wait_for_start()
            child = subprocess.Popen([sys.executable, "-u", str(HERE / "wowvoice.py"), *sys.argv[1:]])
            log(f"tool started (pid {child.pid})")
            if wait_until_gone(child) == "child":
                log(f"tool exited (code {child.wait()}); starting it again in 5 s")
                child = None
                time.sleep(5)
                continue
            log("Battle.net and WoW are closed: stopping the tool")
            stop(child)
            child = None
    finally:
        if child is not None and child.poll() is None:
            stop(child)


if __name__ == "__main__":
    main()
