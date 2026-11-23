#!/usr/bin/env python3
"""Transcribe every lab recording with Whisper via faster-whisper (CPU, comparison only).

Usage (from ~/my-steam-deck-gets-me, after: source env.sh):
  envs/sherpa/bin/python lab/run_whisper.py RUN_NAME [--model large-v3-turbo] [--prompt FILE]
--prompt FILE: give Whisper the terms (one per line) as its initial prompt (its form of boosting).
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from faster_whisper import WhisperModel

LAB = Path(__file__).resolve().parent
META = LAB / "recordings" / "meta.json"
RESULTS = LAB / "results"


def load_audio(path):
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return soxr.resample(audio, rate, 16000, quality="VHQ").astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--prompt")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--set", default="", help="test set: recordings-SET/ -> results-SET/")
    args = parser.parse_args()
    global META, RESULTS
    if args.set:
        META = LAB / f"recordings-{args.set}" / "meta.json"
        RESULTS = LAB / f"results-{args.set}"

    prompt = None
    if args.prompt:
        terms = [l.strip() for l in Path(args.prompt).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        prompt = "WoW chat. " + ", ".join(terms) + "."
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    meta = json.loads(META.read_text(encoding="utf-8"))
    results, seconds = {}, {}
    for key, info in sorted(meta.items()):
        audio = load_audio(META.parent / info["file"])
        start = time.perf_counter()
        segments, _ = model.transcribe(audio, language="en", beam_size=5, initial_prompt=prompt,
                                       vad_filter=False, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        spent = time.perf_counter() - start
        results[key], seconds[key] = text, round(spent, 3)
        print(f"{key} {spent:5.2f}s  {text}", flush=True)
    results["_seconds"] = seconds
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {RESULTS.name}/{args.run}.json")


if __name__ == "__main__":
    main()
