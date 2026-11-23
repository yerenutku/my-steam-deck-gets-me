#!/usr/bin/env python3
"""wowvoice: dictate into WoW chat with one Steam Deck back button (default R4).

  hold               talk -> text into chat in the last channel -> countdown -> sent
  double-press+hold  the WowVoice addon shows the channel ring (pick with the right stick), talk, release
  double-press       correction (stops the countdown; the addon shows the correction menu)
  tap                send now (during the countdown, or in --send-mode wait)
Send modes: countdown (default 2 s, a draining bar in WoW), immediate, wait (tap to send).

Engine: Parakeet unified-en on the GPU (Vulkan, transcribe.cpp) + names correction (namefix.py);
--engine qwen: Qwen3-ASR 1.7B with names as context (more accurate, ~3-4 s in game).
The tool signals the addon with Ctrl+Shift+F9..F12 (type nothing) and presses Enter itself to send.
It types only when WoW is the active window; otherwise the text goes to the clipboard.
Every dictation is kept in service/history/ (audio + json), newest HISTORY_KEEP.

Run (from ~/my-steam-deck-gets-me, ONE instance only):  envs/sherpa/bin/python service/wowvoice.py
        [--send-mode countdown|immediate|wait] [--countdown 2] [--engine parakeet|qwen] [--no-addon]
"""

import argparse
import collections
import json
import shutil
import signal as os_signal
import subprocess
import sys
import threading
import re
import time
import wave
from pathlib import Path

import numpy as np

os_environ = __import__("os").environ
os_environ.setdefault("DISPLAY", ":0")            # started by systemd before/without the desktop session

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from deckbutton import ButtonWatcher  # noqa: E402
from vkeyboard import VirtualKeyboard  # noqa: E402
from namefix import NameFixer, load_common  # noqa: E402

_WOW = sorted((Path.home() / ".local/share/Steam/steamapps/compatdata").glob(
    "*/pfx/drive_c/Program Files (x86)/World of Warcraft/_forever_"))      # the compatdata id differs per install
WOW_SV = (_WOW[0] if _WOW else Path.home() / "World of Warcraft/_forever_") / "WTF/Account"


def context_file():
    """The WowVoice addon's saved file (written by WoW on /reload and logout); newest if several accounts."""
    files = list(WOW_SV.glob("*/SavedVariables/MySteamDeckGetsMe.lua")) or list(WOW_SV.glob("*/SavedVariables/WowVoice.lua"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def saved_send_mode(path):
    """The send mode the player chose on the wheel, as the addon saved it: (mode, countdown) or (None, None).
    The addon is the one place the player sees and changes it, so it wins over the tool's own settings.json."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, AttributeError):
        return None, None
    m = re.search(r'\["mode"\]\s*=\s*"(countdown|immediate|wait)"', text)
    c = re.search(r'\["countdown"\]\s*=\s*([\d.]+)', text)
    return (m.group(1) if m else None), (float(c.group(1)) if c else None)


def read_context(path):
    """The addon's voice context: ["ctx"] = "term;term;…" and ["ctxAt"] = unix time."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], None
    m = re.search(r'\["ctx"\]\s*=\s*"((?:[^"\\]|\\.)*)"', text)
    at = re.search(r'\["ctxAt"\]\s*=\s*(\d+)', text)
    if not m:
        return [], None
    raw = re.sub(r"\\(.)", r"\1", m.group(1))
    return [t.strip() for t in raw.split(";") if t.strip()], int(at.group(1)) if at else None
from ring import RingSession  # noqa: E402

MODELS = {
    "parakeet": ROOT / "models/gguf/handy-computer--parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-F16.gguf",
    "qwen": ROOT / "models/gguf/handy-computer--Qwen3-ASR-1.7B-gguf/Qwen3-ASR-1.7B-Q8_0.gguf",
}
VAD_MODEL = ROOT / "models/silero_vad.onnx"
HISTORY = HERE / "history"
HISTORY_KEEP = 200
POPUPS = False                     # KDE popups (see Feedback.note); the addon's card replaces them
SYSTEM_DUCK = True                 # stream ducking (WoW audio stream to 8 %), being tested by the user
                                   # turns WoW's own sound sliders down instead (user 2026-11-22)
SETTINGS = HERE / "settings.json"     # send mode + countdown, changed from the ring's Options
RATE = 48000                 # mic rate; resampled to 16 kHz for the models
PREROLL, TAIL = 0.5, 0.2     # seconds kept before the press / after the release
MIN_HOLD = 0.25              # shorter presses are taps (tap = send now, double tap = correction)
DOUBLE_TAP = 0.35            # max gap between two taps
BOUNCE = 0.04                # a press or a gap shorter than this is switch bounce, not a gesture
MAX_SECONDS = 30
WOW_WINDOW = "World of Warcraft"
CHAT_MAX = 255               # WoW chat line limit


_cache = {}


def _cached(key, seconds, fn):
    now = time.monotonic()
    if key not in _cache or now - _cache[key][0] > seconds:
        _cache[key] = (now, fn())
    return _cache[key][1]


def desktop_mode():
    """Desktop Mode = KDE Plasma runs. In Game Mode (gamescope) there's no KDE: no popups, no window titles."""
    return _cached("desktop", 5, lambda: subprocess.run(["pgrep", "-x", "plasmashell"],
                                                        capture_output=True).returncode == 0)


def wow_running():
    """The tool only reacts while WoW runs: other games keep the button to themselves."""
    return _cached("wow", 2, lambda: subprocess.run(["pgrep", "-f", "Wow.exe"], capture_output=True).returncode == 0)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ----------------------------------------------------------------- feedback (popup + beeps)
class Feedback:
    def __init__(self):
        self.note_id = None
        self.beeps = {}
        cache = ROOT / ".cache" / "beeps"
        cache.mkdir(parents=True, exist_ok=True)
        for name, freqs in {"start": [880], "stop": [660], "done": [660, 990], "nothing": [330], "error": [220, 220]}.items():
            path = cache / f"{name}.wav"
            if not path.exists():
                parts = []
                for f in freqs:
                    t = np.arange(int(0.08 * 16000)) / 16000
                    tone = 0.25 * np.sin(2 * np.pi * f * t) * np.hanning(len(t))
                    parts += [tone, np.zeros(int(0.04 * 16000))]
                pcm = (np.concatenate(parts) * 32767).astype(np.int16)
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(pcm.tobytes())
            self.beeps[name] = path

    def beep(self, name):
        subprocess.Popen(["pw-play", str(self.beeps[name])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def note(self, text, timeout_ms=0):
        """KDE popups are switched off: WoW in fullscreen suppresses them, and the WowVoice addon shows its own
        listening/transcribing card in the game (Desktop and Game Mode). Kept for --popups."""
        if not POPUPS or not desktop_mode():
            return
        cmd = ["notify-send", "-a", "wowvoice", "-p", "-t", str(timeout_ms), "-u", "low"]
        if self.note_id:
            cmd += ["-r", self.note_id]

        def show():
            try:
                out = subprocess.run(cmd + [text], capture_output=True, text=True, timeout=3).stdout.strip()
                self.note_id = out or self.note_id
            except (OSError, subprocess.TimeoutExpired):
                pass
        threading.Thread(target=show, daemon=True).start()


# ----------------------------------------------------------------- game sound down while talking
class Ducker:
    """While R4 is held, WoW's own sound goes down to DUCK of its level (our beeps stay loud); released = back.
    Finds WoW's audio stream by name; without it, the whole output is lowered instead. The saved levels are kept
    in a file, so a crash while talking is undone at the next start."""

    STATE = ROOT / ".cache" / "duck_state.json"
    DUCK = 0.08                                       # 8 % of the current level (user: "5-10 %")

    def __init__(self):
        self.saved = None
        self.restore()                                # left over from a crash?

    @staticmethod
    def _wow_streams():
        try:
            out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True,
                                 timeout=2).stdout
            streams = json.loads(out or "[]")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []
        found = []
        for st in streams:
            props = st.get("properties", {})
            who = " ".join(str(props.get(k, "")) for k in ("application.name", "application.process.binary",
                                                         "media.name", "node.name")).lower()
            if "world of warcraft" in who:
                pct = [int(v["value_percent"].rstrip("%")) for v in st.get("volume", {}).values()] or [100]
                found.append((st["index"], max(pct)))
        return found

    def duck(self):
        if not SYSTEM_DUCK or self.saved is not None:
            return
        streams = self._wow_streams()
        if streams:
            log(f"sound down: WoW's audio stream(s) {streams} -> {round(self.DUCK * 100)} %")
            self.saved = {"streams": streams}
            for idx, pct in streams:
                subprocess.run(["pactl", "set-sink-input-volume", str(idx), f"{max(1, round(pct * self.DUCK))}%"],
                               capture_output=True)
        else:                                         # WoW's stream not found: the whole output, after the beep
            try:
                vol = float(subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True,
                                           text=True, timeout=2).stdout.split()[1])
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                return
            log(f"sound down: WoW's audio stream not found -> system volume {vol} -> {round(self.DUCK * 100)} %")
            self.saved = {"master": vol}
            time.sleep(0.15)
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol * self.DUCK:.3f}"], capture_output=True)
        try:
            self.STATE.write_text(json.dumps(self.saved))
        except OSError:
            pass

    def restore(self):
        saved = self.saved
        if saved is None and self.STATE.exists():
            try:
                saved = json.loads(self.STATE.read_text())
                log(f"restoring the game volume left down by a crash: {saved}")
            except (OSError, ValueError):
                saved = None
        if saved:
            for idx, pct in saved.get("streams", []):
                subprocess.run(["pactl", "set-sink-input-volume", str(idx), f"{pct}%"], capture_output=True)
            if "master" in saved:
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{saved['master']:.3f}"],
                               capture_output=True)
        self.saved = None
        self.STATE.unlink(missing_ok=True)


# ----------------------------------------------------------------- microphone (on demand)
class Mic:
    """Microphone on demand with a PREROLL ring buffer: the stream opens at a press (~85 ms) and closes after LINGER
    seconds without recording; every press restarts that time (user's rule: 2 minutes). LINGER = None keeps it open
    for the tool's whole awake time (the sleeper only runs the tool while Battle.net/WoW run).
    WATCH: in v0.4.22 (LINGER 5 s) the first two recordings after a cold start in Game Mode were digital silence
    after 0.3 s (cause unknown; Desktop Mode cold starts heard test beeps from 0.3 s on). Log line "mic: opened
    (cold)" marks such presses: if exactly those come back as "no speech", go back to LINGER = None.
    Every press gets its OWN recording (a list of 20 ms blocks); a release closes it TAIL seconds later, so a quick
    next press can never take or empty the previous recording (that race gave "empty PCM buffer")."""

    BLOCK = 0.02
    LINGER = 120.0                  # seconds idle before the stream closes; None = never (see above)

    def __init__(self):
        self.lock = threading.Lock()
        self.ring = collections.deque(maxlen=int(PREROLL / self.BLOCK) + 2)
        self.open = []                      # [recording, end_len or None] still receiving blocks
        self.proc = None
        self.idle_since = None

    def _ensure(self):
        """Start the stream if it isn't running (lock held)."""
        if self.proc is None:
            self.ring.clear()
            self.idle_since = None
            self.proc = subprocess.Popen(["pw-record", "-a", "--rate", str(RATE), "--channels", "1", "--format",
                                          "s16", "--latency", "20ms", "-"],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _close_stream(self):
        """Stop the stream (lock held); its reader thread sees the end and reaps it."""
        proc, self.proc = self.proc, None
        if proc is not None:
            proc.kill()

    def _read(self, proc):
        size = int(RATE * self.BLOCK) * 2
        while True:
            block = proc.stdout.read(size)
            if not block:
                break
            # (exact zeros are normal: SteamOS sets the Deck codec's noise gate, ADC DRC Noise Gate 4:1 below
            #  -50 dB, so a quiet room gives digital silence. Only a WHOLE dictation of zeros is suspicious.)
            with self.lock:
                if proc is not self.proc:
                    break
                self.ring.append(block)
                still = []
                for rec in self.open:
                    rec[0].append(block)
                    if rec[1] is None or len(rec[0]) < rec[1]:
                        still.append(rec)
                self.open = still
                if self.open:
                    self.idle_since = None
                elif self.idle_since is None:
                    self.idle_since = time.monotonic()
                elif self.LINGER is not None and time.monotonic() - self.idle_since > self.LINGER:
                    self._close_stream()            # nothing to record: microphone off
                    log(f"mic: closed after {self.LINGER:g} s without recording")
                    break
        proc.kill()
        proc.wait()
        with self.lock:
            if proc is self.proc:                   # the stream died on its own
                self.proc = None
                if self.open:
                    log("microphone stream ended; reopening")
                    self._ensure()

    def start(self):
        with self.lock:
            self._ensure()

    def restart(self):
        """Restart the stream (after a dictation that was entirely digital silence)."""
        with self.lock:
            self._close_stream()

    def stop(self):
        with self.lock:
            self.open.clear()
            self._close_stream()

    def press(self):
        """Start a recording (the microphone opens if it was off); returns its handle."""
        with self.lock:
            if self.proc is None:
                log("mic: opened (cold)")
            self._ensure()
            self.idle_since = None
            rec = [list(self.ring), None]
            self.open.append(rec)
            return rec

    def release(self, rec):
        """Close a recording TAIL seconds from now."""
        if rec is None:
            return
        with self.lock:
            rec[1] = len(rec[0]) + int(TAIL / self.BLOCK)

    def take(self, rec):
        """Wait until the recording is closed, return its samples."""
        if rec is None:
            return np.zeros(0, dtype=np.int16)
        deadline = time.monotonic() + TAIL + 1.0
        while time.monotonic() < deadline:
            with self.lock:
                if rec not in self.open:
                    break
            time.sleep(0.02)
        with self.lock:
            if rec in self.open:
                self.open.remove(rec)
            data = b"".join(rec[0])
        return np.frombuffer(data, dtype=np.int16)


def to16k(pcm48):
    import soxr
    return np.ascontiguousarray(soxr.resample(pcm48.astype(np.float32) / 32768, RATE, 16000, quality="VHQ"),
                                dtype=np.float32)


_VAD = {}


def speech_seconds(audio16):
    import sherpa_onnx
    if "vad" in _VAD:
        vad = _VAD["vad"]
        vad.reset()
        return _count_speech(vad, audio16, _VAD["window"])
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(VAD_MODEL)
    cfg.silero_vad.min_silence_duration = 0.3
    cfg.silero_vad.min_speech_duration = 0.15
    cfg.silero_vad.threshold = 0.5
    cfg.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=MAX_SECONDS + 5)
    _VAD.update(vad=vad, window=cfg.silero_vad.window_size)
    return _count_speech(vad, audio16, cfg.silero_vad.window_size)


def _count_speech(vad, audio16, w):
    total = 0
    for i in range(0, len(audio16), w):
        vad.accept_waveform(audio16[i:i + w])
        while not vad.empty():
            total += len(vad.front.samples)
            vad.pop()
    vad.flush()
    while not vad.empty():
        total += len(vad.front.samples)
        vad.pop()
    return total / 16000


# ----------------------------------------------------------------- the engine
class Engine:
    def __init__(self, names_file, kind="parakeet"):
        import transcribe_cpp as tc
        tc.set_log_callback(lambda level, msg: level in (2, 3) and print("engine:", msg.strip(), flush=True))
        self.tc = tc
        self.kind = kind
        self.names_file = Path(names_file)
        self.names_mtime = None
        self.prompt = None
        device = next(d for d in tc.backends() if d.kind == "vulkan")
        self.model = tc.Model(str(MODELS[kind]), device=device)
        self.session = self.model.session(n_threads=4, n_ctx=4096 if kind == "qwen" else 0)
        self.device = device.description

    def refresh_names(self):
        """Re-read names.txt and the addon's saved voice context (quests, bags, vendors, people) when they change."""
        mtime = self.names_file.stat().st_mtime if self.names_file.exists() else None
        ctx_file = context_file()
        ctx_mtime = ctx_file.stat().st_mtime if ctx_file else None
        if (mtime, ctx_mtime) != self.names_mtime:
            self.names_mtime = (mtime, ctx_mtime)
            terms = []
            if mtime:
                terms = [l.strip() for l in self.names_file.read_text(encoding="utf-8").splitlines()
                         if l.strip() and not l.strip().startswith("#")]
            ctx, saved_at = read_context(ctx_file) if ctx_file else ([], None)
            if ctx:
                common = load_common()
                ctx = [t for t in ctx if " " in t or t.lower().replace("'", "") not in common]
                log(f"voice context: {len(ctx)} terms from the addon (saved "
                    f"{time.strftime('%H:%M', time.localtime(saved_at)) if saved_at else '?'})")
            plural_ok = set(ctx)
            terms += ctx
            self.prompt = "World of Warcraft chat." + (" Vocabulary: " + ", ".join(terms) + "." if terms else "")
            self.fixer = NameFixer(terms, plural_ok=plural_ok)
            log(f"names: {len(terms)} terms from {self.names_file.name}")

    def transcribe(self, audio16):
        self.refresh_names()
        if self.kind != "qwen":                       # Parakeet: names are applied afterwards (namefix)
            return self.session.run(audio16, language="en").text.strip()
        try:
            return self.session.run(audio16, language="en", prompt=self.prompt).text.strip()
        except self.tc.OutputTruncated:
            return ""


def clean(text):
    text = " ".join(text.split())
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]                  # chat lines rarely end with a period
    return text[:CHAT_MAX]


def active_window():
    """The active window's title. In Game Mode only the game is on screen: WoW running = WoW in front."""
    if not desktop_mode():
        return WOW_WINDOW if wow_running() else ""
    try:
        return subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True,
                              text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def to_clipboard(text):
    """KDE's clipboard (Klipper) over D-Bus in Desktop Mode; wl-copy/xclip if present."""
    q = shutil.which("qdbus6") or shutil.which("qdbus")
    cmds = [[q, "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", text]] if q else []
    cmds += [["wl-copy", text]] if shutil.which("wl-copy") else []
    for cmd in cmds:
        try:
            if subprocess.run(cmd, capture_output=True, timeout=3).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def save_history(pcm48, entry):
    HISTORY.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with wave.open(str(HISTORY / f"{stamp}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(pcm48.tobytes())
    (HISTORY / f"{stamp}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
    old = sorted(HISTORY.glob("*.wav"))[:-HISTORY_KEEP]
    for wav in old:
        wav.unlink(missing_ok=True)
        wav.with_suffix(".json").unlink(missing_ok=True)


# ----------------------------------------------------------------- R4 gestures
class Gestures(threading.Thread):
    """Turns raw button down/up into gestures, put on `out` (a queue.Queue):
       ("hold_start", double)       button held past MIN_HOLD (double = it was the 2nd press of a double press)
       ("hold_end", double, held, released_at, recording)
       ("tap",)                      one short press, no second press within DOUBLE_TAP
       ("double_tap",)               two short presses
    """

    def __init__(self, out):
        super().__init__(daemon=True)
        import queue
        self.raw = queue.Queue()
        self.out = out

    def push(self, down, rec=None):
        self.raw.put((down, time.monotonic(), time.time(), rec))

    def run(self):
        import queue
        down_at = None          # monotonic time of the current press
        second = False          # current press is the 2nd of a double press
        holding = False         # hold_start already sent for the current press
        tap_waiting = None      # monotonic time a short first press ended (waiting for a 2nd press)
        pending_up = None       # (mono, wall, rec) of a release that might still be contact bounce
        last_up = -1.0          # monotonic time of the last real release

        def finish_up(mono, wall, rec):
            nonlocal down_at, holding, second, tap_waiting, last_up
            held = mono - down_at
            if holding:
                self.out.put(("hold_end", second, held, wall, rec))
            elif second:
                self.out.put(("double_tap",))
            else:
                tap_waiting = mono
            down_at, holding, second, last_up = None, False, False, mono

        while True:
            now = time.monotonic()
            waits = []
            if pending_up is not None:
                waits.append(pending_up[0] + BOUNCE - now)
            if down_at is not None and not holding and pending_up is None:
                waits.append(down_at + MIN_HOLD - now)
            if down_at is None and tap_waiting is not None:
                waits.append(tap_waiting + DOUBLE_TAP - now)
            timeout = max(0.0, min(waits)) if waits else None
            try:
                down, mono, wall, rec = self.raw.get(timeout=timeout)
            except queue.Empty:
                now = time.monotonic()
                if pending_up is not None and now >= pending_up[0] + BOUNCE:
                    finish_up(*pending_up)                   # no new press came: it was a real release
                    pending_up = None
                elif down_at is not None and not holding and now >= down_at + MIN_HOLD:
                    holding = True
                    self.out.put(("hold_start", second))
                elif down_at is None and tap_waiting is not None and now >= tap_waiting + DOUBLE_TAP:
                    tap_waiting = None
                    self.out.put(("tap",))
                continue
            if down:
                if pending_up is not None:                   # pressed again within BOUNCE: bounce, same press
                    pending_up = None
                    continue
                if down_at is not None:                      # (a second "down" without an up: ignore)
                    continue
                if mono - last_up < BOUNCE:                  # a flicker right after a release: ignore it
                    self.ignore_next_up = True
                    continue
                second = tap_waiting is not None and mono - tap_waiting <= DOUBLE_TAP
                tap_waiting = None
                down_at, holding = mono, False
            else:
                if getattr(self, "ignore_next_up", False):
                    self.ignore_next_up = False
                    continue
                if down_at is None:
                    continue
                pending_up = (mono, wall, rec)               # decided after BOUNCE: bounce or real release


# ----------------------------------------------------------------- main loop
# Signals to the WowVoice addon (Ctrl+Shift+F<n>, keys that type nothing); ring signals 1-3 are in ring.py.
# The text goes into the addon's OWN dictation box (opened by SIG_BOX only when no text field has focus;
# otherwise the text lands in the focused field, e.g. a bag or auction house search). The addon sends it on
# SIG_SEND (a real key press = hardware event, which WoW requires for /say and channels). The tool never
# presses Enter or touches WoW's chat box, so it can't get out of step with it.
SIG_BOX, SIG_COUNTDOWN, SIG_SEND, SIG_CORRECT = 4, 5, 6, 7
SIG_REPLACE, SIG_REPLACE_DONE = 8, 9               # correction: the typed word replaces the selected word
SIG_LISTEN, SIG_WORKING, SIG_IDLE = 10, 11, 12      # the in-game indicator: listening / transcribing / done
HELLO = 9                     # Shift+F9 (ring highlights use Shift+F1-8): "the tool runs" -> addon shows Ready
HELLO_AFTER = tuple(range(3, 91, 3))  # every 3 s for 90 s after a UI load (loading screens eat keys); the
                                      # addon only reacts to the first one it gets
OVERLAY, APP_OLDER, ADDON_OLDER = 10, 11, 12   # Shift+F10: L4 shows / hides the button overlay;
                                               # F11 / F12: the addon says which side must be updated (compat numbers)


def main():
    import queue
    parser = argparse.ArgumentParser()
    parser.add_argument("--button", default=None, choices=["L4", "R4", "L5", "R5"])
    parser.add_argument("--engine", default="parakeet", choices=["parakeet", "qwen"],
                        help="parakeet: GPU ~0.3 s + names correction; qwen: GPU, names as context, ~3-4 s in game")
    parser.add_argument("--names", default=str(HERE / "wow_terms.txt"))
    parser.add_argument("--send-mode", default=None, choices=["countdown", "immediate", "wait"],
                        help="countdown: send after --countdown s (a tap sends now, a double tap stops it); "
                             "immediate: send at once; wait: a tap sends")
    parser.add_argument("--countdown", type=float, default=None)
    parser.add_argument("--no-addon", action="store_true",
                        help="without the WowVoice addon: press Enter to open chat instead of the addon signal")
    parser.add_argument("--any-window", action="store_true", help="type even if WoW isn't the active window")
    args = parser.parse_args()
    try:
        saved = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        saved = {}
    sv_mode, sv_countdown = saved_send_mode(context_file())   # the addon's saved choice wins
    args.send_mode = args.send_mode or sv_mode or saved.get("send_mode", "countdown")
    args.countdown = args.countdown or sv_countdown or saved.get("countdown", 2.0)
    args.button = args.button or saved.get("button", "R4")

    def save_settings():
        SETTINGS.write_text(json.dumps({"send_mode": args.send_mode, "countdown": args.countdown,
                                        "button": args.button}, indent=1))

    def set_option(item, mode, seconds):
        args.send_mode = mode
        if seconds:
            args.countdown = seconds
        save_settings()
        log(f"option: {item} -> send mode {args.send_mode}, countdown {args.countdown:g} s")
        fb.note(f"⚙️ Send: {item}", 2000)

    fb = Feedback()
    ducker = Ducker()
    fb.note("wowvoice: loading speech model…", 0)
    engine = Engine(args.names, args.engine)
    engine.refresh_names()
    import soundfile as sf                                         # warm up on real speech: an LLM
    warm_file = HERE / "warmup.wav"                                # decoder can loop on silence
    if warm_file.exists():
        warm, _ = sf.read(str(warm_file), dtype="int16")
        log(f"warm-up: \"{engine.transcribe(to16k(warm))}\"")
    elif args.engine == "parakeet":                                # no own recording (public copy): soft noise
        warm = np.random.default_rng(0).normal(0, 300, RATE).astype(np.int16)
        log(f"warm-up (noise): \"{engine.transcribe(to16k(warm))}\"")
    else:
        log("warm-up skipped: Qwen needs service/warmup.wav (a few seconds of your own speech)")
    keyboard = VirtualKeyboard()
    mic = Mic()                                       # opens at the first press
    gestures_q = queue.Queue()
    gestures = Gestures(gestures_q)
    gestures.start()
    # text typed into the box and not sent yet; correcting = the addon's correction menu is open
    pending = {"text": None, "deadline": None, "correcting": False}
    ring = {"session": None}

    current = {"rec": None, "ignored": False}
    def on_button(down):
        if down:
            # Only for WoW: in Game Mode it must be running (only the game is on screen); in Desktop Mode it
            # must be the active window (another window in front = the button isn't ours, no beep).
            if not args.any_window and (not wow_running() or (desktop_mode() and WOW_WINDOW not in active_window())):
                current["ignored"] = True
                return
            current["ignored"] = False
            current["rec"] = mic.press()              # every press records (+ pre-roll)
            gestures.push(True)
        else:
            if current["ignored"]:
                return
            rec, current["rec"] = current["rec"], None
            mic.release(rec)
            gestures.push(False, rec)

    def on_pad(name):                                 # A / B on the controller (the addon acts on them)
        gestures_q.put(("pad", name))

    def wow_active():
        return args.any_window or WOW_WINDOW in active_window()

    def signal(n):
        if not args.no_addon and wow_active():
            keyboard.signal(n)

    state = {"holding": False}                        # R4 held right now (main thread sets it)
    jobs = queue.Queue()                              # transcriptions, one after another, off the main thread

    def idle():
        if not state["holding"]:                      # a new press already shows "Listening": leave it
            signal(SIG_IDLE)

    def send_pending(reason):
        if pending["text"] is not None and wow_active():
            keyboard.signal(SIG_SEND)                     # the addon sends its box (no-op if it was closed)
            fb.beep("done")
            fb.note(f"📨 {pending['text']}", 1500)
            log(f"sent ({reason}): \"{pending['text']}\"")
        pending.update(text=None, deadline=None, correcting=False)

    def transcribe_clip(held, released_at, double, rec):
        """Returns (pcm, text, entry); text is None when there's nothing to type (already reported)."""
        pcm = mic.take(rec)
        if len(pcm) < 0.3 * RATE:
            log(f"recording too short ({len(pcm) / RATE:.2f} s)")
            fb.beep("nothing")
            idle()
            return pcm, None, None
        fb.beep("stop")
        fb.note("⏳ Transcribing…")
        if not state["holding"]:
            signal(SIG_WORKING)
        t0 = time.perf_counter()
        audio = to16k(pcm[: MAX_SECONDS * RATE])
        vad_result = {}
        vad_thread = threading.Thread(target=lambda: vad_result.update(s=speech_seconds(audio)))
        vad_thread.start()                                # silence check runs next to the transcription
        raw = engine.transcribe(audio)
        t2 = time.perf_counter()
        vad_thread.join()
        speech = vad_result.get("s", 1.0)
        peak = int(np.abs(pcm).max()) if len(pcm) else 0
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if len(pcm) else 0.0
        entry = {"held": round(held, 2), "seconds": round(len(audio) / 16000, 2), "speech": round(speech, 2),
                 "released_at": round(released_at, 3), "ring": double, "mode": args.send_mode,
                 "peak": peak, "rms": round(rms)}
        if speech < 0.25:
            log(f"no speech ({held:.1f} s held, level peak {peak} rms {rms:.0f})")
            fb.beep("nothing")
            fb.note("No speech heard", 1500)
            idle()
            save_history(pcm, {**entry, "text": "", "result": "no speech"})
            return pcm, None, entry
        fixed, changes = engine.fixer.fix(raw) if raw else (raw, [])
        text = clean(fixed)
        entry.update(text=text, raw=raw, namefix=changes, asr_s=round(t2 - t0, 2))
        if changes:
            log(f"names: {changes}")
        if not text:
            log(f"nothing recognised ({held:.1f} s held, {speech:.1f} s speech, level peak {peak})")
            fb.beep("nothing")
            fb.note("Nothing recognised", 1500)
            idle()
            save_history(pcm, {**entry, "result": "empty"})
            return pcm, None, entry
        return pcm, text, entry

    def dictate(held, released_at, double, rec):
        pcm, text, entry = transcribe_clip(held, released_at, double, rec)
        if text is None:
            return
        window = active_window()
        entry["window"] = window
        if not (args.any_window or WOW_WINDOW in window):
            to_clipboard(text)
            entry["result"] = "clipboard (WoW not active)"
            fb.beep("error")
            fb.note(f"📋 WoW not active, copied: {text}", 4000)
            log(f"{entry['result']}: \"{text}\"")
            save_history(pcm, entry)
            return
        entry["text_ready_s"] = round(time.time() - released_at, 2)
        if pending["text"] is not None:                   # an earlier text still waits in the box: send it first
            send_pending("new dictation")
            time.sleep(0.1)
        if args.no_addon:
            keyboard.enter()                              # without the addon: WoW's chat (only if closed!)
        else:
            keyboard.signal(SIG_BOX)                      # addon: open its box (unless a text field has focus)
        time.sleep(0.15)
        keyboard.type(text)
        entry["typed_at"] = round(time.time(), 3)
        entry["release_to_typed_s"] = round(entry["typed_at"] - released_at, 2)
        pending.update(text=text, correcting=False)
        if args.send_mode == "immediate":
            time.sleep(0.05)
            send_pending("immediate")
        else:
            if not args.no_addon:
                keyboard.signal(SIG_COUNTDOWN)            # addon: draining bar (or "A / tap R4" in wait mode)
            if args.send_mode == "countdown":
                pending["deadline"] = time.monotonic() + args.countdown
                gestures_q.put(("wake",))                 # the main loop starts timing the countdown
                fb.note(f"⏱ {text}", int(args.countdown * 1000))
            else:
                fb.beep("done")
                fb.note(f"✋ tap {args.button} to send: {text}", 4000)
        entry["result"] = "typed"
        log(f"typed: \"{text}\"  (held {held:.1f} s, release→chat {entry['release_to_typed_s']} s, "
            f"asr+vad {entry['asr_s']})")
        save_history(pcm, entry)

    def say_word_again(held, released_at, rec):
        """Correction mode: the new word replaces the word selected in the addon's correction menu."""
        pcm, text, entry = transcribe_clip(held, released_at, False, rec)
        if text is None:
            return
        word = text.strip().strip(".,!?;:")
        if not word:
            idle()
            return
        signal(SIG_REPLACE)                               # addon: select the word, so typing replaces it
        time.sleep(0.08)
        keyboard.type(word)
        time.sleep(0.05)
        signal(SIG_REPLACE_DONE)                          # addon: re-read the words, offer it as the choice
        idle()
        entry["result"] = "word replaced"
        log(f"correction: word said again -> \"{word}\"")
        save_history(pcm, entry)

    def handle(g):
        kind = g[0]
        if kind == "wake":
            return
        log("gesture: " + " ".join(str(round(x, 2) if isinstance(x, float) else x) for x in g[:3]))
        if kind == "key":                                 # Esc / Enter on a real keyboard: the box closed / was sent
            if pending["text"] is not None and wow_active():
                log(("dropped by Esc" if g[1] == "esc" else "sent by Enter") + " in the box")
                pending.update(text=None, deadline=None, correcting=False)
            return
        if kind == "pad" and g[1] == "L4":                # the addon's button overlay (for videos)
            if wow_active() and not args.no_addon:
                keyboard.highlight(OVERLAY)
            return
        if kind == "pad":                                 # the addon acted on A / B; keep our state in step
            if pending["correcting"]:
                pending["correcting"] = False             # A = corrections done, B = undone: back to the box
            elif pending["text"] is not None:
                log(("sent" if g[1] == "A" else "dropped") + f" by {g[1]} in the box")
                pending.update(text=None, deadline=None)
        elif kind == "hold_start":
            double = g[1]
            state["holding"] = True
            if pending["correcting"]:
                fb.beep("start")
                fb.note("🎙 Say the word again…")
                signal(SIG_LISTEN)
                ducker.duck()
                return
            if pending["text"] is not None:
                send_pending("new dictation")
            if double and wow_active() and not args.no_addon:
                ring["session"] = RingSession(watcher, keyboard, set_option, log)
                ring["session"].start()                   # addon: show the ring
            fb.beep("start")
            fb.note("🎙 Listening…" + (" (pick a channel)" if double else ""))
            signal(SIG_LISTEN)
            ducker.duck()                                 # game sound down while talking
        elif kind == "hold_end":
            _, double, held, released_at, rec = g
            state["holding"] = False
            ducker.restore()
            if ring["session"] is not None:
                ring["session"].finish()
                ring["session"] = None
            if pending["correcting"]:
                jobs.put((say_word_again, (held, released_at, rec)))
            else:
                jobs.put((dictate, (held, released_at, double, rec)))
        elif kind == "tap":
            if pending["text"] is not None:
                send_pending("tap")
        elif kind == "double_tap":
            if pending["text"] is not None and not pending["correcting"]:
                signal(SIG_CORRECT)                       # addon: stop the bar, open the correction menu
                pending.update(deadline=None, correcting=True)
                fb.note("✏️ Correction: ←→ word · ↑↓ choice · hold R4 = say it again · A = done · B = undo", 4000)
                log("double tap: correction menu")
            else:
                log("double tap: nothing to correct")

    def worker():
        while True:
            fn, a = jobs.get()
            try:
                fn(*a)
            except Exception:
                import traceback
                log("ERROR:\n" + traceback.format_exc())
                fb.beep("error")

    threading.Thread(target=worker, daemon=True).start()
    from keywatch import KeyWatcher
    KeyWatcher(lambda k: gestures_q.put(("key", k))).start()
    watcher = ButtonWatcher(args.button, on_button, on_pad)
    watcher.start()
    log(f"ready: {args.button}: hold = talk, double-press & hold = ring, double-press = correction. "
        f"Send mode: {args.send_mode}" + (f" {args.countdown:g} s" if args.send_mode == "countdown" else "")
        + f". Engine: {args.engine} on {engine.device}.")
    fb.note(f"wowvoice ready: hold {args.button} to talk", 4000)

    def greeter():
        """Say hello to the addon after every WoW login and /reload, so it can show "WowVoice ready" (and tell the
        player when the tool is missing). Triggers (inotify, no polling) are files WoW always writes: entering the
        world from the character list writes WTF/SavedVariables/Blizzard_GlueSavedVariables.lua; /reload (and logout)
        writes the account's SavedVariables/WowVoice.lua. The UI is up a few seconds later; hellos at HELLO_AFTER."""
        from inotify import Inotify
        IN_CLOSE_WRITE, IN_MOVED_TO = 0x008, 0x080
        wtf = WOW_SV.parent
        folders = [wtf / "SavedVariables"] + sorted(WOW_SV.glob("*/SavedVariables"))
        folders = [f for f in folders if f.is_dir()]
        if not folders:
            log(f"greeter: no WoW SavedVariables folder under {wtf}; no ready message")
            return
        ino = Inotify()
        for f in folders:
            ino.watch(f, IN_CLOSE_WRITE | IN_MOVED_TO)
        triggers = {"Blizzard_GlueSavedVariables.lua", "MySteamDeckGetsMe.lua", "WowVoice.lua"}
        plan = [time.monotonic() + d for d in (1, 8, 20)] if wow_running() else []   # started while WoW runs
        give_up = time.monotonic() + 180                  # retries while WoW isn't in front end here
        while True:
            events = ino.read(max(0.0, plan[0] - time.monotonic()) if plan else None)
            if any(name in triggers for _, name, _ in events):
                plan = [time.monotonic() + d for d in HELLO_AFTER]
                give_up = time.monotonic() + 180
            for folder, name, _ in events:
                if name in ("MySteamDeckGetsMe.lua", "WowVoice.lua"):   # /reload or logout: the addon's send mode
                    mode, countdown = saved_send_mode(folder / name)
                    if mode and (mode, countdown or args.countdown) != (args.send_mode, args.countdown):
                        args.send_mode, args.countdown = mode, countdown or args.countdown
                        save_settings()
                        log(f"send mode from the addon: {args.send_mode} {args.countdown:g} s")
            while plan and plan[0] <= time.monotonic():
                plan.pop(0)
                if wow_active():
                    keyboard.highlight(HELLO)
                    if len(plan) + 1 in (len(HELLO_AFTER), 3):  # log only the first of a round
                        log("hello: sending to the addon")
                    mine = updater.local_release().get("compat", 1)
                    theirs = [updater.addon_compat(d) for d in updater.addon_dirs()]
                    if any(c != mine for c in theirs) and not update["misfit_said"]:
                        time.sleep(0.3)
                        keyboard.highlight(APP_OLDER if max(theirs) > mine else ADDON_OLDER)
                        update["misfit_said"] = True
                        log(f"addon (compat {theirs}) and app (compat {mine}) don't fit: told the addon")
                elif not plan and time.monotonic() < give_up:
                    plan.append(time.monotonic() + 5)        # WoW not in front (Desktop Mode): try again soon

    import updater
    update = {"misfit_said": False}

    threading.Thread(target=updater.auto_update, args=(wow_running, log), daemon=True).start()

    def update_watch():
        """Check again every time WoW starts (inotify: Wow.exe opened), not only when the app wakes up."""
        from inotify import IN_OPEN, Inotify
        folders = [d.parents[2] for d in updater.addon_dirs()]
        if not folders or not updater.is_installed_copy():
            return
        ino = Inotify()
        for f in folders:
            ino.watch(f, IN_OPEN)
        while True:
            if any(n.lower() == "wow.exe" for _, n, _ in ino.read()):
                time.sleep(3)
                updater.auto_update(wow_running, log, wow_just_started=True)
                time.sleep(60)                            # one check per start
                while ino.read(0):
                    pass

    threading.Thread(target=update_watch, daemon=True).start()

    threading.Thread(target=greeter, daemon=True).start()

    def on_term(*_):
        """The sleeper stops us (Battle.net and WoW closed). Clean up in a thread: raising inside the handler can
        break a lock the main thread is waiting on ("release unlocked lock")."""
        def cleanup():
            import os
            try:
                ducker.restore()                       # game sound back if R4 was held
                mic.stop()
                keyboard.close()
                log("stopped: microphone closed, model unloaded")
            finally:
                os._exit(0)
        threading.Thread(target=cleanup, daemon=True).start()

    os_signal.signal(os_signal.SIGTERM, on_term)
    _main_loop(gestures_q, handle, send_pending, pending, ducker, fb)


def _main_loop(gestures_q, handle, send_pending, pending, ducker, fb):
    import queue
    while True:
        timeout = None
        if pending["deadline"] is not None:
            timeout = max(0.0, pending["deadline"] - time.monotonic())
        try:
            g = gestures_q.get(timeout=timeout)
        except queue.Empty:
            send_pending("countdown")
            continue
        try:
            handle(g)
        except Exception:
            import traceback
            log("ERROR:\n" + traceback.format_exc())
            ducker.restore()
            fb.beep("error")


if __name__ == "__main__":
    main()
