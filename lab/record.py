#!/usr/bin/env python3
"""Accuracy-lab recorder: shows one test line at a time; hold SPACE to record it.

Keys:  hold SPACE = record (release to save, then it moves to the next line)
       Left / Right = previous / next line     P = play back this line's recording
       Esc = quit

The mic runs continuously so each recording also keeps PREROLL seconds from just
before you pressed SPACE (no clipped first word) and TAIL seconds after release.
Saves 48 kHz mono 16-bit WAVs to recordings/NNN.wav and details to recordings/meta.json.
python3 record.py --set fresh  -> lines-fresh.txt, saved to recordings-fresh/.
"""

import array
import collections
import sys
import json
import subprocess
import threading
import time
import tkinter as tk
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
# --set NAME records a separate test set: lines-NAME.txt -> recordings-NAME/
SET = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else ""
LINES_FILE = HERE / (f"lines-{SET}.txt" if SET else "lines.txt")
OUT_DIR = HERE / (f"recordings-{SET}" if SET else "recordings")
META_FILE = OUT_DIR / "meta.json"

RATE = 48000
BYTES_PER_SEC = RATE * 2
CHUNK = BYTES_PER_SEC // 50          # 20 ms
PREROLL = 0.5
TAIL = 0.3
RELEASE_DEBOUNCE_MS = 120            # key autorepeat sends release/press pairs


def load_lines():
    lines = []
    for raw in LINES_FILE.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#"):
            lines.append(raw)
    return lines


def load_meta():
    try:
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Mic:
    """Reads the default PipeWire source continuously into a pre-roll ring buffer."""

    def __init__(self):
        self.proc = subprocess.Popen(
            ["pw-record", "-a", "--rate", str(RATE), "--channels", "1",
             "--format", "s16", "--latency", "20ms", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.lock = threading.Lock()
        self.ring = collections.deque(maxlen=int(PREROLL * 50))
        self.capture = None          # list of chunks while recording
        self.stop_at = None          # monotonic time to stop (release + TAIL)
        self.finished = None         # bytes of the last completed recording
        self.level = 0.0
        self.peak = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            data = self.proc.stdout.read(CHUNK)
            if not data:
                return
            samples = array.array("h", data[: len(data) // 2 * 2])
            peak = max((abs(s) for s in samples), default=0)
            with self.lock:
                self.level = peak / 32768
                if self.capture is not None:
                    self.capture.append(data)
                    self.peak = max(self.peak, peak)
                    if self.stop_at is not None and time.monotonic() >= self.stop_at:
                        self.finished = b"".join(self.capture)
                        self.capture = None
                        self.stop_at = None
                else:
                    self.ring.append(data)

    def start(self):
        with self.lock:
            self.capture = list(self.ring)
            self.ring.clear()
            self.stop_at = None
            self.finished = None
            self.peak = 0

    def stop(self):
        with self.lock:
            if self.capture is not None and self.stop_at is None:
                self.stop_at = time.monotonic() + TAIL

    def take_finished(self):
        with self.lock:
            data, self.finished = self.finished, None
            return data, self.peak

    def close(self):
        self.proc.terminate()


class App:
    def __init__(self, root):
        self.root = root
        self.lines = load_lines()
        self.meta = load_meta()
        self.index = self._first_unrecorded()
        self.mic = Mic()
        self.recording = False
        self.release_job = None
        self.pressed_at = None
        self.status = "Hold SPACE and read the line. Release when done."

        root.title("WoW voice lab: recorder")
        root.configure(bg="#14161a")
        root.geometry("1100x560")
        self.progress = tk.Label(root, font=("Sans", 16), fg="#9aa3ad", bg="#14161a")
        self.progress.pack(pady=(24, 0))
        self.text = tk.Label(root, font=("Sans", 30, "bold"), fg="#f2f2f2", bg="#14161a",
                             wraplength=1000, justify="center")
        self.text.pack(expand=True, padx=40)
        self.meter = tk.Canvas(root, width=600, height=22, bg="#22262c", highlightthickness=0)
        self.meter.pack(pady=8)
        self.state = tk.Label(root, font=("Sans", 22, "bold"), bg="#14161a")
        self.state.pack(pady=6)
        self.info = tk.Label(root, font=("Sans", 14), fg="#c8ccd2", bg="#14161a", wraplength=1000)
        self.info.pack(pady=(0, 10))
        tk.Label(root, font=("Sans", 12), fg="#7d858f", bg="#14161a",
                 text="hold SPACE = record   ←/→ = previous/next   P = play back   Esc = quit"
                 ).pack(pady=(0, 18))

        root.bind("<KeyPress-space>", self.on_press)
        root.bind("<KeyRelease-space>", self.on_release)
        root.bind("<Left>", lambda e: self.move(-1))
        root.bind("<Right>", lambda e: self.move(1))
        root.bind("<Key-p>", lambda e: self.play())
        root.bind("<Escape>", lambda e: self.quit())
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.refresh()
        self.tick()

    def _first_unrecorded(self):
        for i in range(len(self.lines)):
            if f"{i + 1:03d}" not in self.meta:
                return i
        return 0

    def key(self):
        return f"{self.index + 1:03d}"

    def refresh(self):
        done = sum(1 for i in range(len(self.lines)) if f"{i + 1:03d}" in self.meta)
        self.progress.config(text=f"Line {self.index + 1} of {len(self.lines)}   ·   {done} recorded")
        if self.index >= len(self.lines):
            self.text.config(text="All lines recorded. Thank you!\nYou can close this window.")
        else:
            self.text.config(text=self.lines[self.index])
        if self.recording:
            self.state.config(text="● RECORDING", fg="#ff5a5a")
        elif self.key() in self.meta and self.index < len(self.lines):
            self.state.config(text="✓ recorded (hold SPACE to redo)", fg="#6fd38a")
        else:
            self.state.config(text="ready", fg="#9aa3ad")
        self.info.config(text=self.status)

    def tick(self):
        level = self.mic.level
        self.meter.delete("all")
        color = "#ff5a5a" if level > 0.95 else ("#6fd38a" if level > 0.05 else "#5a6470")
        self.meter.create_rectangle(0, 0, int(600 * min(1.0, level ** 0.5)), 22, fill=color, width=0)
        data, peak = self.mic.take_finished()
        if data is not None:
            self.save(data, peak)
        self.root.after(30, self.tick)

    def on_press(self, _event):
        if self.release_job is not None:          # autorepeat: still held
            self.root.after_cancel(self.release_job)
            self.release_job = None
            return
        if self.recording or self.index >= len(self.lines):
            return
        self.recording = True
        self.pressed_at = time.monotonic()
        self.mic.start()
        self.status = "Speak now… release SPACE when you're done."
        self.refresh()

    def on_release(self, _event):
        if self.recording and self.release_job is None:
            self.release_job = self.root.after(RELEASE_DEBOUNCE_MS, self.really_released)

    def really_released(self):
        self.release_job = None
        held = time.monotonic() - self.pressed_at - RELEASE_DEBOUNCE_MS / 1000
        self.held = max(0.0, held)
        self.mic.stop()

    def save(self, data, peak):
        self.recording = False
        if self.index >= len(self.lines):
            return
        key = self.key()
        OUT_DIR.mkdir(exist_ok=True)
        path = OUT_DIR / f"{key}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(data)
        seconds = len(data) / BYTES_PER_SEC
        self.meta[key] = {
            "text": self.lines[self.index], "file": path.name, "seconds": round(seconds, 2),
            "held_seconds": round(getattr(self, "held", 0.0), 2), "preroll": PREROLL,
            "tail": TAIL, "peak": round(peak / 32768, 3), "rate": RATE,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        META_FILE.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")
        warn = ""
        if peak / 32768 > 0.98:
            warn = "  ⚠ too loud (clipped), maybe redo a bit further away"
        elif peak / 32768 < 0.05:
            warn = "  ⚠ very quiet, maybe redo a bit louder/closer"
        self.status = f"Saved line {self.index + 1} ({seconds:.1f}s).{warn}  ← to go back and redo."
        self.index += 1
        self.refresh()

    def move(self, step):
        if self.recording:
            return
        self.index = max(0, min(len(self.lines), self.index + step))
        self.status = ""
        self.refresh()

    def play(self):
        path = OUT_DIR / f"{self.key()}.wav"
        if path.exists() and not self.recording:
            subprocess.Popen(["pw-play", str(path)], stderr=subprocess.DEVNULL)

    def quit(self):
        self.mic.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
