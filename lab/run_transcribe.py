#!/usr/bin/env python3
"""Transcribe every lab recording with transcribe.cpp (ggml engine; Vulkan GPU or CPU).

Python bindings: transcribe-cpp (+ transcribe-cpp-native, which ships the Vulkan build).
Names: --names FILE passes `vocabulary=` (or `prompt=` for models with a context prompt) when the
model supports it; the script prints what the model supports.

Usage (from ~/wowvoice, after: source env.sh):
  envs/sherpa/bin/python lab/run_transcribe.py MODEL.gguf RUN_NAME [--names FILE] [--cpu]
        [--threads N] [--set NAME]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import transcribe_cpp as tc

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from run_sherpa import load_audio  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--names")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--ctx", type=int, default=0, help="decoder context tokens (0 = engine default); raise for long name lists")
    parser.add_argument("--set", default="")
    args = parser.parse_args()

    meta_file = LAB / (f"recordings-{args.set}" if args.set else "recordings") / "meta.json"
    results_dir = LAB / (f"results-{args.set}" if args.set else "results")
    kind = "cpu" if args.cpu else "vulkan"
    device = next(d for d in tc.backends() if d.kind == kind)
    model = tc.Model(args.model, device=device)
    feats = {f: model.supports(f) for f in ("vocabulary", "context_prompt")}
    print("device:", device.description, "| supports:", feats, flush=True)
    extra = {}
    if args.names:
        terms = [l.strip() for l in Path(args.names).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        if feats["context_prompt"]:
            extra["prompt"] = "World of Warcraft chat. Vocabulary: " + ", ".join(terms) + "."
        elif feats["vocabulary"]:
            extra["vocabulary"] = terms
        else:
            print("model supports no names/context: running without", flush=True)

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    with model.session(n_threads=args.threads, n_ctx=args.ctx) as session:
        def run(audio):
            try:
                return session.run(np.ascontiguousarray(audio, dtype=np.float32), language="en", **extra).text.strip()
            except tc.OutputTruncated:                        # e.g. an LLM model looping on silence
                print("   (output truncated)", flush=True)
                return ""
        first = next(iter(sorted(meta.items())))[1]["file"]
        run(load_audio(meta_file.parent / first))            # warm-up on real speech
        results, seconds = {}, {}
        for key, info in sorted(meta.items()):
            audio = load_audio(meta_file.parent / info["file"])
            start = time.perf_counter()
            text = run(audio)
            spent = time.perf_counter() - start
            results[key], seconds[key] = text, round(spent, 3)
            print(f"{key} {spent:5.2f}s  {text}", flush=True)
    results["_seconds"] = seconds
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {results_dir.name}/{args.run}.json")


if __name__ == "__main__":
    main()
