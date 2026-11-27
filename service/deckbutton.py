"""Watch one Steam Deck button through the controller's raw HID reports (read-only, no root).

Steam keeps working normally: hidraw can be read by several programs at once. Byte/bit positions
come from Decktation's deck_hid.py (MIT): reports are 64 bytes, report[0:3] == 01 00 09.
"""

import glob
import os
import threading
import time

BUTTONS = {"L4": (13, 1), "R4": (13, 2), "L5": (9, 7), "R5": (10, 0)}
PAD = {"A": (8, 7), "B": (8, 5)}            # watched too: the tool must know when the box was sent / dropped
# (View = byte 9 bit 4, Menu = byte 9 bit 6, if ever needed: SDL's Steam Deck map, checked 2026-11-23)


def find_deck_hidraw():
    for path in sorted(glob.glob("/dev/hidraw*")):
        try:
            with open(f"/sys/class/hidraw/{os.path.basename(path)}/device/uevent") as f:
                props = dict(line.rstrip().split("=", 1) for line in f if "=" in line)
        except OSError:
            continue
        if props.get("HID_ID", "").upper().endswith("000028DE:00001205") and props.get("HID_PHYS", "").endswith("/input2"):
            return path
    return None


class ButtonWatcher(threading.Thread):
    """Calls on_change(pressed: bool) whenever the chosen button goes down or up.
    Also keeps the right stick's latest position in self.stick = (x, y), each -1..1, y up = positive
    (bytes 52-55 of the Deck report: SDL's SteamDeckStatePacket_t sRightStickX/Y, after the 4-byte header)."""

    def __init__(self, button, on_change, on_pad=None):
        super().__init__(daemon=True)
        self.byte, self.bit = BUTTONS[button]
        self.on_change = on_change
        self.on_pad = on_pad                       # on_pad("A" / "B") when that button goes down
        self.pad_down = {name: False for name in PAD}
        self.pressed = False
        self.stick = (0.0, 0.0)            # right stick
        self.lstick = (0.0, 0.0)           # left stick (bytes 48-51)

    def set_button(self, button):
        """Switch the talk button while running (Options ring: R4 <-> L4)."""
        self.byte, self.bit = BUTTONS[button]
        self.pressed = False

    def run(self):
        while True:
            path = find_deck_hidraw()
            if not path:
                time.sleep(2)
                continue
            try:
                fd = os.open(path, os.O_RDWR)        # hid-steam wants read/write even for input
            except OSError:
                time.sleep(2)
                continue
            try:
                while True:
                    report = os.read(fd, 64)
                    if len(report) != 64 or report[0] != 1 or report[1] != 0 or report[2] != 0x09:
                        continue
                    self.lstick = (int.from_bytes(report[48:50], "little", signed=True) / 32767,
                                   int.from_bytes(report[50:52], "little", signed=True) / 32767)
                    self.stick = (int.from_bytes(report[52:54], "little", signed=True) / 32767,
                                  int.from_bytes(report[54:56], "little", signed=True) / 32767)
                    if self.on_pad:
                        for name, (byte, bit) in PAD.items():
                            now = bool(report[byte] >> bit & 1)
                            if now and not self.pad_down[name]:
                                self.on_pad(name)
                            self.pad_down[name] = now
                    down = bool(report[self.byte] >> self.bit & 1)
                    if down != self.pressed:
                        self.pressed = down
                        self.on_change(down)
            except OSError:
                time.sleep(1)                         # controller went away (sleep/resume): rescan
            finally:
                os.close(fd)
