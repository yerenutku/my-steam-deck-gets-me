"""Watches real keyboards for Esc and Enter, so the tool knows when the player closed (Esc) or sent (Enter) the
addon's box by hand: the addon can't tell the tool (WoW's sandbox), but the key presses are visible here.

Reads /dev/input/event* (readable for the logged-in user through logind's ACL); our own virtual keyboard
("wowvoice keyboard") and devices without an Esc key (mice, the power button) are skipped. Rescans every few
seconds, so a keyboard plugged in later is picked up.
"""

import os
import select
import struct
import threading
import time
from pathlib import Path

EV_KEY = 0x01
KEYS = {1: "esc", 28: "enter", 96: "enter"}           # KEY_ESC, KEY_ENTER, KEY_KPENTER
EVENT = struct.Struct("llHHi")
OWN = "wowvoice keyboard"


def _has_esc(name):
    try:
        caps = (Path("/sys/class/input") / name / "device/capabilities/key").read_text().split()
    except OSError:
        return False
    bits = int("".join(w.rjust(16, "0") for w in caps), 16) if caps else 0
    return bool(bits >> 1 & 1)


class KeyWatcher(threading.Thread):
    def __init__(self, on_key):
        super().__init__(daemon=True)
        self.on_key = on_key
        self.fds = {}                                     # path -> fd

    def _scan(self):
        for dev in sorted(Path("/dev/input").glob("event*")):
            path = str(dev)
            if path in self.fds:
                continue
            try:
                name = (Path("/sys/class/input") / dev.name / "device/name").read_text().strip()
            except OSError:
                continue
            if name == OWN or not _has_esc(dev.name):
                continue
            try:
                self.fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                pass

    def run(self):
        last_scan = 0.0
        while True:
            if time.monotonic() - last_scan > 5:
                self._scan()
                last_scan = time.monotonic()
            if not self.fds:
                time.sleep(1)
                continue
            ready, _, _ = select.select(list(self.fds.values()), [], [], 2)
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:                           # unplugged
                    for p, f in list(self.fds.items()):
                        if f == fd:
                            os.close(f)
                            del self.fds[p]
                    continue
                for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, i)
                    if etype == EV_KEY and value == 1 and code in KEYS:
                        self.on_key(KEYS[code])
