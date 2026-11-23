"""The channel ring: the tool decides WHICH slot (it reads the right stick from the controller), the
WowVoice addon decides WHAT a slot is (channels, names, commands: only WoW knows those) and draws it.

8 slots clockwise from the top (design: design/handoff, concept B). Push the stick towards a slot (highlight),
let it go back to the middle = pick; letting go of R4 also picks the highlighted slot. In every sub-ring the
NW slot (8, the grey stone sector) is "Back". Options holds the send modes and "Commands".
Signals to the addon (keys that type nothing):
  Shift+F1..F8     highlight slot 1..8
  Ctrl+Shift+F1    ring open          Ctrl+Shift+F2  ring close         Ctrl+Shift+F3  pick the highlighted slot
The camera stays still through Steam Input (the user's mode shift on R4 turns the right joystick into a
D-pad without commands while R4 is held), so nothing here holds sticks or plays movement keys.
"""

import math
import threading
import time

# must match WowVoice.lua (TOP / sub-rings)
TOP = ["Say", "Party", "Guild", "Whisper", "Friends", "Recent", "World", "Options"]   # Party = Raid/BG when in one
SUBRINGS = {"Whisper", "Friends", "Recent", "World", "Options"}   # their content comes from WoW
SUB_SLOTS = 8
BACK = 7                                                          # NW slot in every sub-ring
OPTIONS = ["2 s", "3 s", "5 s", "Wait for me", "Send immediately"]           # Options slots 1-5 (static)
COMMANDS_SLOT = 6                                                 # Options slot 7 (W, next to Back) opens Commands
HYSTERESIS = 4.0                                                  # degrees: no flicker at sector borders
OPTION_VALUES = {"2 s": ("countdown", 2.0), "3 s": ("countdown", 3.0), "5 s": ("countdown", 5.0),
                 "Wait for me": ("wait", None), "Send immediately": ("immediate", None)}
PUSH, CENTER = 0.55, 0.25          # stick length to highlight / to count as back in the middle
SIG_OPEN, SIG_CLOSE, SIG_PICK = 1, 2, 3


def slot_of(x, y, n, current=None):
    """n slots clockwise from the top; None while the stick isn't pushed far enough. Keeps `current` until the
    stick is HYSTERESIS degrees past the sector border."""
    if math.hypot(x, y) < PUSH:
        return None
    angle = math.degrees(math.atan2(x, y)) % 360
    width = 360 / n
    if current is not None:
        off = (angle - current * width + 180) % 360 - 180
        if abs(off) <= width / 2 + HYSTERESIS:
            return current
    return int((angle + width / 2) // width) % n


class RingSession:
    def __init__(self, watcher, keyboard, on_option, log):
        self.watcher, self.keyboard, self.on_option, self.log = watcher, keyboard, on_option, log
        self.level, self.slots = "top", len(TOP)
        self.highlight = None
        self.closed = False
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.keyboard.signal(SIG_OPEN)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            x, y = self.watcher.stick
            s = slot_of(x, y, self.slots, self.highlight)
            with self.lock:
                if self.closed:
                    return
                if s is not None:
                    if s != self.highlight:
                        self.keyboard.highlight(s + 1)        # the addon draws it
                    self.highlight = s
                elif math.hypot(x, y) < CENTER and self.highlight is not None:
                    self._commit()
            time.sleep(0.02)

    def _commit(self):
        k, self.highlight = self.highlight, None
        self.keyboard.signal(SIG_PICK)                    # the addon picks its highlighted slot
        if self.level == "top":
            item = TOP[k]
            self.log(f"ring: {item}")
            if item in SUBRINGS:
                self.level, self.slots = item, SUB_SLOTS
            else:
                self._close()                             # a channel: the addon remembers it for the box
        else:
            self.log(f"ring {self.level}: slot {k + 1}")
            if k == BACK:                                 # back up one level
                self.level = "Options" if self.level == "Commands" else "top"
                self.slots = len(TOP) if self.level == "top" else SUB_SLOTS
            elif self.level == "Options" and k == COMMANDS_SLOT:
                self.level = "Commands"
            else:
                if self.level == "Options" and k < len(OPTIONS):
                    self.on_option(OPTIONS[k], *OPTION_VALUES[OPTIONS[k]])
                self._close()                             # a name, channel, command or option

    def _close(self):
        if not self.closed:
            self.closed = True
            self.keyboard.signal(SIG_CLOSE)

    def finish(self):
        """R4 was let go: pick the highlighted slot (if any) and close the ring."""
        self.stop.set()
        self.thread.join(timeout=1)
        with self.lock:
            if not self.closed and self.highlight is not None:
                self._commit()
            self._close()
