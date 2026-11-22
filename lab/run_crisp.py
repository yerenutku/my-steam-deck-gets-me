#!/usr/bin/env python3
"""Transcribe every lab recording with CrispASR (ggml engine; Vulkan GPU or CPU).

Starts `crispasr --server` with the model loaded once, then sends each recording over HTTP
(as the real dictation service would), so the timing is the wait after release, not model loading.

Names: --hotwords FILE boosts the terms during Parakeet TDT decoding (beam search recommended),
       --context FILE gives Qwen3-ASR the terms as free text ("World of Warcraft chat. Vocabulary: ...").

Usage (from ~/wowvoice, after: source env.sh):
  envs/sherpa/bin/python lab/run_crisp.py MODEL.gguf RUN_NAME [--backend parakeet|qwen3-1.7b]
        [--beam N] [--hotwords FILE --boost F] [--context FILE] [--cpu] [--threads N] [--set NAME]
"""

import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import soundfile as sf

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from run_sherpa import load_audio  # noqa: E402  (48 kHz -> 16 kHz, same as the other runners)

CRISPASR = LAB.parent / "tools" / "crispasr" / "crispasr-linux-x86_64-vulkan" / "crispasr"
PORT = 8790


def terms(path):
    return [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def wav_bytes(audio):
    buf = io.BytesIO()
    sf.write(buf, audio, 16000, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--backend")
    parser.add_argument("--beam", type=int, default=0)
    parser.add_argument("--hotwords")
    parser.add_argument("--boost", type=float, default=2.0)
    parser.add_argument("--context")
    parser.add_argument("--cpu", action="store_true", help="no GPU (for comparison)")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--set", default="", help="test set: recordings-SET/ -> results-SET/")
    args = parser.parse_args()

    meta_file = LAB / (f"recordings-{args.set}" if args.set else "recordings") / "meta.json"
    results_dir = LAB / (f"results-{args.set}" if args.set else "results")

    cmd = [str(CRISPASR), "--server", "--port", str(PORT), "-m", args.model, "-t", str(args.threads), "-l", "en"]
    if args.backend:
        cmd += ["--backend", args.backend]
    if args.beam:
        cmd += ["-bs", str(args.beam)]
    if args.cpu:
        cmd += ["-ng"]
    log = open(LAB.parent / ".cache" / f"{args.run}.log", "w")
    server = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(600):                                  # model load (+ warm-up) up to 5 min
            if server.poll() is not None:
                raise SystemExit(f"crispasr exited ({server.returncode}); see .cache/crisp-{args.run}.log")
            try:
                if requests.get(f"{url}/health", timeout=1).ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        fields = {"language": "en", "response_format": "json"}
        if args.hotwords:
            # CrispASR v0.8.55 bug: its hotword tokenizer ignores SentencePiece's word-start marker "▁",
            # so plain names never match what Parakeet emits. Adding the marker ourselves fixes it.
            fields["hotwords"] = ",".join("▁" + t.replace(" ", "▁") for t in terms(args.hotwords))
            fields["hotwords_boost"] = str(args.boost)
        if args.context:
            fields["context"] = "World of Warcraft chat. Vocabulary: " + ", ".join(terms(args.context)) + "."

        def run(audio):
            r = requests.post(f"{url}/inference", data=fields,
                              files={"file": ("a.wav", wav_bytes(audio), "audio/wav")}, timeout=300)
            r.raise_for_status()
            return r.json().get("text", "").strip()

        import numpy as np
        run(np.zeros(16000, dtype=np.float32))               # warm-up
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        results, seconds = {}, {}
        for key, info in sorted(meta.items()):
            audio = load_audio(meta_file.parent / info["file"])
            start = time.perf_counter()
            text = run(audio)
            spent = time.perf_counter() - start
            results[key], seconds[key] = text, round(spent, 3)
            print(f"{key} {spent:5.2f}s  {text}", flush=True)
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    results["_seconds"] = seconds
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {results_dir.name}/{args.run}.json")


if __name__ == "__main__":
    main()
