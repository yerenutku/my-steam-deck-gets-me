#!/usr/bin/env python3
"""While-gaming test: how much does dictation slow WoW down, and how much does WoW slow dictation down?

Run while WoW is open (FPS counter: Ctrl+R in WoW). Loads one engine once, idles for a baseline,
then transcribes a random fresh-set recording every GAP seconds. A KDE notification pops up at each
transcription so you know when to look. Logs GPU busy % and CPU busy % every 100 ms to
lab/results-game/<label>-TIME.csv (+ .json summary) and prints per-round timings.

Engines:
  qwen  Qwen3-ASR 1.7B Q8_0 on the GPU (Vulkan, transcribe.cpp), names as context   -> envs/sherpa
  nemo  Parakeet unified-en on the CPU (NeMo), beam 4 + name boosting                -> envs/nemo

Usage (from ~/wowvoice):
  envs/sherpa/bin/python lab/game_test.py --engine qwen [--names lab/names.txt] [--label NAME]
  envs/nemo/bin/python   lab/game_test.py --engine nemo [--threads 3]
  common: [--rounds 10] [--gap 8] [--baseline 30] [--no-popup]
"""

import argparse
import csv
import json
import random
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

LAB = Path(__file__).resolve().parent
ROOT = LAB.parent
QWEN = ROOT / "models/gguf/handy-computer--Qwen3-ASR-1.7B-gguf/Qwen3-ASR-1.7B-Q8_0.gguf"
GPU_BUSY = Path("/sys/class/drm/card0/device/gpu_busy_percent")
LAB_SECONDS = {"qwen": 2.62, "nemo": 1.97}          # lab avg on the fresh set, names-big, no WoW


def load_audio(path):
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        try:
            import soxr
            audio = soxr.resample(audio, rate, 16000, quality="VHQ")
        except ImportError:
            from scipy.signal import resample_poly
            audio = resample_poly(audio, 1, rate // 16000)
    return np.ascontiguousarray(audio, dtype=np.float32)


def read_terms(path):
    return [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def cpu_times():
    v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    idle = v[3] + v[4]
    return sum(v), idle


def popup(text):
    subprocess.Popen(["notify-send", "-a", "wowvoice test", "-t", "2500", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_qwen(names, threads):
    import transcribe_cpp as tc
    prompt = "World of Warcraft chat. Vocabulary: " + ", ".join(read_terms(names)) + "."
    device = next(d for d in tc.backends() if d.kind == "vulkan")
    model = tc.Model(str(QWEN), device=device)
    session = model.session(n_threads=threads, n_ctx=4096)

    def run(audio):
        return session.run(audio, language="en", prompt=prompt).text.strip()
    return run, f"Qwen3-ASR 1.7B on {device.description}", (model, session)


def make_nemo(names, threads):
    import logging
    import sys
    import torch
    sys.path.insert(0, str(LAB))
    import run_nemo
    torch.set_num_threads(threads)
    logging.getLogger("nemo_logger").setLevel(logging.ERROR)
    from nemo.collections.asr.models import ASRModel
    path = next(ROOT.glob("models/hf/hub/models--nvidia--parakeet-unified-en-0.6b/snapshots/*/parakeet-unified-en-0.6b.nemo"))
    model = ASRModel.restore_from(str(path), map_location="cpu").eval()
    run_nemo.configure(model, argparse.Namespace(boost=names, context_score=1.0, beam=4, alpha=1.0))

    def run(audio):
        with torch.inference_mode():
            return run_nemo.text_of(model.transcribe([audio], batch_size=1, verbose=False))
    return run, f"Parakeet unified-en (NeMo, CPU, {threads} threads)", model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["qwen", "nemo"], default="qwen")
    parser.add_argument("--names", default=str(LAB / "names-big.txt"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--gap", type=float, default=8.0)
    parser.add_argument("--baseline", type=float, default=30.0)
    parser.add_argument("--label", default="")
    parser.add_argument("--no-popup", action="store_true")
    args = parser.parse_args()

    out_dir = LAB / "results-game"
    out_dir.mkdir(exist_ok=True)
    label = args.label or f"{args.engine}-{Path(args.names).stem}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = out_dir / f"{label}-{stamp}.csv"
    t0 = time.time()
    phase = {"name": "loading"}
    stop = threading.Event()

    def sampler():
        last_total, last_idle = cpu_times()
        with open(log_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["unix_time", "seconds", "phase", "gpu_busy_percent", "cpu_busy_percent"])
            while not stop.is_set():
                time.sleep(0.1)
                try:
                    gpu = int(GPU_BUSY.read_text().strip())
                except (OSError, ValueError):
                    gpu = -1
                total, idle = cpu_times()
                cpu = 100.0 * (1 - (idle - last_idle) / max(1, total - last_total))
                last_total, last_idle = total, idle
                now = time.time()
                w.writerow([f"{now:.2f}", f"{now - t0:.2f}", phase["name"], gpu, f"{cpu:.0f}"])

    threading.Thread(target=sampler, daemon=True).start()

    meta = json.loads((LAB / "recordings-fresh" / "meta.json").read_text(encoding="utf-8"))
    clips = [(k, load_audio(LAB / "recordings-fresh" / v["file"])) for k, v in sorted(meta.items())]
    run, what, _keep = (make_qwen if args.engine == "qwen" else make_nemo)(args.names, args.threads)
    run(clips[0][1])                                          # warm-up on speech
    print(f"loaded {what}; names: {Path(args.names).name} ({len(read_terms(args.names))} terms).\n"
          f"Baseline: {args.baseline:.0f} s idle - note your normal FPS now.", flush=True)
    if not args.no_popup:
        popup(f"Baseline {args.baseline:.0f} s: note your normal FPS")
    phase["name"] = "baseline"
    time.sleep(args.baseline)
    rows = []
    for i in range(args.rounds):
        key, audio = random.choice(clips)
        if not args.no_popup:
            popup(f"Transcribing {i + 1}/{args.rounds} - watch FPS")
        phase["name"] = f"transcribe-{i + 1}"
        start = time.perf_counter()
        text = run(audio)
        spent = time.perf_counter() - start
        phase["name"] = "idle"
        rows.append((i + 1, key, round(spent, 2), round(len(audio) / 16000, 1)))
        print(f"round {i + 1:2}: line {key} ({len(audio) / 16000:4.1f} s audio) took {spent:5.2f} s  {text}",
              flush=True)
        time.sleep(args.gap)
    stop.set()
    time.sleep(0.3)

    load = {}
    with open(log_path) as f:
        for r in csv.DictReader(f):
            p = "transcribe" if r["phase"].startswith("transcribe") else r["phase"]
            load.setdefault(p, {"gpu": [], "cpu": []})
            load[p]["gpu"].append(int(r["gpu_busy_percent"]))
            load[p]["cpu"].append(float(r["cpu_busy_percent"]))
    print("\nbusy % (average):      GPU    CPU")
    for p, v in load.items():
        if p != "loading":
            print(f"  {p:18} {sum(v['gpu']) / len(v['gpu']):6.1f} {sum(v['cpu']) / len(v['cpu']):6.1f}")
    times = [r[2] for r in rows]
    print(f"transcription time while gaming: avg {sum(times) / len(times):.2f} s, max {max(times):.2f} s "
          f"(lab without WoW, 245 names: {LAB_SECONDS[args.engine]:.2f} s)")
    summary = {"engine": what, "names": Path(args.names).name, "rounds": rows,
               "busy": {p: {k: sum(x) / len(x) for k, x in v.items()} for p, v in load.items()}}
    (out_dir / f"{label}-{stamp}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"saved results-game/{label}-{stamp}.csv + .json")


if __name__ == "__main__":
    main()
