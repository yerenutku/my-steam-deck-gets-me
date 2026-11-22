#!/usr/bin/env python3
"""Streaming test: feed each recording in 100 ms mic-sized chunks, as if live.

The model transcribes while "you talk". Measured:
  sec/line (_seconds) = wait after the last audio arrives (release) until the final text
  rtf                 = total compute / audio length (must be < 1 to keep up live)

Usage (from ~/wowvoice, after: source env.sh):
  envs/sherpa/bin/python lab/run_sherpa_stream.py MODEL_DIR RUN_NAME
        [--hotwords FILE --bpe-vocab FILE --score S] [--paths N] [--threads N]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from run_sherpa import load_audio, pick  # noqa: E402

META = LAB / "recordings" / "meta.json"
RESULTS = LAB / "results"
CHUNK = 1600          # 100 ms at 16 kHz
TAIL = 0.8            # silence fed at the end so the last chunk gets decoded


def make(args):
    d = Path(args.model)
    options = dict(tokens=str(d / "tokens.txt"), encoder=pick(d, "encoder"), decoder=pick(d, "decoder"),
                   joiner=pick(d, "joiner"), num_threads=args.threads, sample_rate=16000,
                   feature_dim=128, decoding_method="greedy_search")
    if args.hotwords:
        terms = [l.strip() for l in Path(args.hotwords).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        clean = LAB.parent / ".cache" / f"hotwords-{args.run}.txt"
        clean.parent.mkdir(exist_ok=True)
        clean.write_text("\n".join(terms) + "\n", encoding="utf-8")
        options.update(decoding_method="modified_beam_search", max_active_paths=args.paths,
                       hotwords_file=str(clean), hotwords_score=args.score,
                       modeling_unit="bpe", bpe_vocab=args.bpe_vocab)
    return sherpa_onnx.OnlineRecognizer.from_transducer(**options)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--hotwords")
    parser.add_argument("--bpe-vocab")
    parser.add_argument("--score", type=float, default=1.5)
    parser.add_argument("--paths", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    recognizer = make(args)
    meta = json.loads(META.read_text(encoding="utf-8"))
    results, seconds, rtfs = {}, {}, []
    for key, info in sorted(meta.items()):
        audio = load_audio(LAB / "recordings" / info["file"])
        stream = recognizer.create_stream()
        busy = 0.0
        for i in range(0, len(audio), CHUNK):                 # while talking
            stream.accept_waveform(16000, audio[i:i + CHUNK])
            t = time.perf_counter()
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            busy += time.perf_counter() - t
        t = time.perf_counter()                               # button released
        stream.accept_waveform(16000, np.zeros(int(TAIL * 16000), dtype=np.float32))
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = recognizer.get_result(stream).strip()
        wait = time.perf_counter() - t
        rtfs.append((busy + wait) / (len(audio) / 16000))
        results[key], seconds[key] = text, round(wait, 3)
        print(f"{key} wait {wait:4.2f}s rtf {rtfs[-1]:.2f}  {text}", flush=True)
    results["_seconds"] = seconds
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved results/{args.run}.json  (max rtf {max(rtfs):.2f}, avg {sum(rtfs) / len(rtfs):.2f})")


if __name__ == "__main__":
    main()
