#!/usr/bin/env python3
"""Line up WoW's own frame times (WowVoiceFPS addon) with the game_test.py logs.

For each results-game/*.csv test it reports WoW's FPS during the idle baseline vs during
transcription, plus the worst single frame (a stutter) and the "1% low" FPS.

Usage: python3 lab/fps_analyze.py [--since YYYYmmdd-HHMMSS] [--sv PATH]
The addon data reaches disk only after /reload or logout in WoW.
"""

import argparse
import bisect
import csv
import re
from pathlib import Path

LAB = Path(__file__).resolve().parent
def _find_wow():
    """WoW Forever's folder inside any Proton prefix (the compatdata id differs per install)."""
    hits = sorted((Path.home() / ".local/share/Steam/steamapps/compatdata").glob(
        "*/pfx/drive_c/Program Files (x86)/World of Warcraft/_forever_"))
    return hits[0] if hits else Path.home() / "World of Warcraft/_forever_"


WOW = _find_wow()


def find_sv():
    hits = sorted(WOW.glob("WTF/Account/*/SavedVariables/WowVoiceFPS.lua"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise SystemExit("No WowVoiceFPS.lua yet: /reload in WoW first (that writes the data).")
    return hits[-1]


def load_frames(sv):
    text = sv.read_text(encoding="utf-8", errors="replace")
    anchors_block = re.search(r'\["anchors"\]\s*=\s*\{(.*?)\n\},?\n\["', text, re.S)
    chunks_block = re.search(r'\["chunks"\]\s*=\s*\{(.*?)\n\},?\n\["', text, re.S)
    if not anchors_block or not chunks_block:
        raise SystemExit(f"Could not parse {sv}")
    anchors = [tuple(float(x) for x in m.groups())
               for m in re.finditer(r'\{\s*([\d.]+),\s*(\d+),\s*(\d+),?\s*\}', anchors_block.group(1))]
    durations = []
    for chunk in re.findall(r'"([\d.,]*)"', chunks_block.group(1)):
        durations += [float(x) for x in chunk.split(",") if x]
    if not anchors or not durations:
        raise SystemExit("No frames recorded yet.")
    # frame end times: cumulative durations, placed on the wall clock via the nearest earlier anchor
    cum = [0.0]
    for d in durations:
        cum.append(cum[-1] + d / 1000)
    frames_at = [int(a[2]) for a in anchors]
    times = []
    for k in range(1, len(durations) + 1):
        i = max(0, bisect.bisect_right(frames_at, k) - 1)
        _, unix, ka = anchors[i]
        ka = int(ka)
        if ka > len(durations):
            ka = len(durations)
        times.append(unix + (cum[k] - cum[ka]))
    return times, durations


def window_stats(times, durations, spans):
    sel = [d for t, d in zip(times, durations) if any(a <= t <= b for a, b in spans)]
    total = sum(b - a for a, b in spans)
    if not sel or total <= 0:
        return None
    worst = sorted(sel, reverse=True)
    low1 = worst[max(0, len(worst) // 100 - 1)] if len(worst) >= 100 else worst[0]
    return {"fps": len(sel) / total, "worst_ms": worst[0], "low1_fps": 1000 / low1, "frames": len(sel)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="")
    parser.add_argument("--sv")
    args = parser.parse_args()
    sv = Path(args.sv) if args.sv else find_sv()
    times, durations = load_frames(sv)
    print(f"{sv.name}: {len(durations)} frames, {times[0]:.0f}..{times[-1]:.0f}")
    print(f"{'test':42} {'phase':11} {'FPS':>5} {'1% low':>7} {'worst frame':>12} {'transcribe s':>13}")
    for csv_path in sorted((LAB / "results-game").glob("*.csv")):
        stamp = csv_path.stem[-15:]
        if stamp < args.since:
            continue
        rows = list(csv.DictReader(open(csv_path)))
        if not rows or float(rows[-1]["unix_time"]) < times[0] or float(rows[0]["unix_time"]) > times[-1]:
            continue
        spans = {}
        cur = None
        for r in rows:
            ph = "transcribe" if r["phase"].startswith("transcribe") else r["phase"]
            t = float(r["unix_time"])
            if cur and cur[0] == r["phase"]:
                cur[2] = t
            else:
                if cur:
                    spans.setdefault(cur[3], []).append((cur[1], cur[2]))
                cur = [r["phase"], t, t, ph]
        if cur:
            spans.setdefault(cur[3], []).append((cur[1], cur[2]))
        tr = spans.get("transcribe", [])
        avg_tr = sum(b - a for a, b in tr) / len(tr) if tr else 0
        for ph in ("baseline", "transcribe", "idle"):
            s = window_stats(times, durations, spans.get(ph, []))
            if s:
                print(f"{csv_path.stem:42} {ph:11} {s['fps']:5.1f} {s['low1_fps']:7.1f} {s['worst_ms']:9.0f} ms "
                      f"{(f'{avg_tr:.2f}' if ph == 'transcribe' else ''):>13}")


if __name__ == "__main__":
    main()
