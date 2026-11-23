"""Minimal virtual keyboard through Linux uinput (no root, no compiled modules).

The user `deck` has read/write access to /dev/uinput (ACL). Keys are sent as a real keyboard would,
so it works in Desktop Mode (KWin/Xwayland) and in Game Mode (gamescope). Assumes a US layout.
"""

import fcntl
import os
import struct
import threading
import time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

KEY_ENTER, KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_BACKSPACE, KEY_ESC = 28, 42, 29, 14, 1
KEY_LEFTALT = 56
FKEYS = {1: 59, 2: 60, 3: 61, 4: 62, 5: 63, 6: 64, 7: 65, 8: 66, 9: 67, 10: 68, 11: 87, 12: 88}
_ROWS = {  # char -> keycode (unshifted, shifted) on a US layout
    **{c: (k, False) for c, k in zip("1234567890", range(2, 12))},
    **{c: (k, True) for c, k in zip("!@#$%^&*()", range(2, 12))},
    **{c: (k, False) for c, k in zip("qwertyuiop", range(16, 26))},
    **{c: (k, False) for c, k in zip("asdfghjkl", range(30, 39))},
    **{c: (k, False) for c, k in zip("zxcvbnm", range(44, 51))},
    "-": (12, False), "_": (12, True), "=": (13, False), "+": (13, True),
    "[": (26, False), "{": (26, True), "]": (27, False), "}": (27, True),
    ";": (39, False), ":": (39, True), "'": (40, False), '"': (40, True),
    "`": (41, False), "~": (41, True), "\\": (43, False), "|": (43, True),
    ",": (51, False), "<": (51, True), ".": (52, False), ">": (52, True),
    "/": (53, False), "?": (53, True), " ": (57, False),
}
KEYMAP = dict(_ROWS)
for _c, (_k, _s) in list(_ROWS.items()):
    if _c.isalpha():
        KEYMAP[_c.upper()] = (_k, True)
# common non-ASCII characters a transcript may contain
REPLACE = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", " ": " "}


class VirtualKeyboard:
    def __init__(self, name="wowvoice keyboard", delay=0.0007):
        self.delay = delay
        self.lock = threading.RLock()            # the ring thread and the main loop both press keys
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in range(1, 128):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        # legacy struct uinput_user_dev: name[80], id (bustype, vendor, product, version), ff_effects_max,
        # absmax/absmin/absfuzz/absflat[64] each
        dev = struct.pack("80sHHHHi", name.encode()[:79], 0x06, 0x1209, 0x7777, 1, 0) + b"\0" * (4 * 64 * 4)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.3)                      # let the compositor notice the new keyboard

    def _event(self, etype, code, value):
        now = time.time()
        os.write(self.fd, struct.pack("llHHi", int(now), int((now % 1) * 1e6), etype, code, value))

    def _key(self, code, down):
        self._event(EV_KEY, code, 1 if down else 0)
        self._event(EV_SYN, SYN_REPORT, 0)
        time.sleep(self.delay)

    def tap(self, code, shift=False):
        with self.lock:
            self._tap(code, shift)

    def _tap(self, code, shift=False):
        if shift:
            self._key(KEY_LEFTSHIFT, True)
        self._key(code, True)
        self._key(code, False)
        if shift:
            self._key(KEY_LEFTSHIFT, False)

    def type(self, text):
        """Type text; characters a US keyboard can't produce are replaced or skipped."""
        with self.lock:
            for ch in text:
                ch = REPLACE.get(ch, ch)
                for c in ch:
                    if c in KEYMAP:
                        self._tap(*KEYMAP[c])

    def enter(self):
        self.tap(KEY_ENTER)

    def alt_tab(self):
        """Alt+Tab: switch to the previous window (Desktop Mode, no keyboard needed)."""
        with self.lock:
            self._key(KEY_LEFTALT, True)
            self._tap(15)                          # KEY_TAB
            time.sleep(0.05)
            self._key(KEY_LEFTALT, False)

    def down(self, code):
        with self.lock:
            self._key(code, True)

    def up(self, code):
        with self.lock:
            self._key(code, False)

    def highlight(self, n):
        """Shift+F<n>: the addon highlights ring slot n (types no character)."""
        with self.lock:
            self._key(KEY_LEFTSHIFT, True)
            self._tap(FKEYS[n])
            self._key(KEY_LEFTSHIFT, False)

    def signal(self, n):
        """Ctrl+Shift+F<n>: an invisible signal for the WowVoice addon (types no character)."""
        with self.lock:
            self._key(KEY_LEFTCTRL, True)
            self._key(KEY_LEFTSHIFT, True)
            self._tap(FKEYS[n])
            self._key(KEY_LEFTSHIFT, False)
            self._key(KEY_LEFTCTRL, False)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
