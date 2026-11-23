#!/usr/bin/env python3
"""Transcribe every lab recording with Qwen3-ASR (Hugging Face transformers).

Qwen3-ASR is a speech LLM: an audio encoder + a Qwen3 language model that writes the text
token by token. Names/terms are given as a plain-text context prompt (no boosting tree).

Usage (from ~/my-steam-deck-gets-me, after: source env.sh):
  envs/nemo/bin/python lab/run_qwen.py MODEL RUN_NAME [--names FILE] [--device cpu|cuda]
        [--threads N] [--set NAME] [--dtype float32|bfloat16|float16]
MODEL: Qwen/Qwen3-ASR-0.6B-hf or Qwen/Qwen3-ASR-1.7B-hf. CPU works with the nemo env;
GPU (--device cuda: ROCm uses the "cuda" name) needs envs/gpu.
Writes lab/results[-SET]/RUN_NAME.json like the other runners.
"""

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

LAB = Path(__file__).resolve().parent


def load_audio(path):
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate == 48000:
        audio = resample_poly(audio, 1, 3).astype(np.float32)
    elif rate != 16000:
        raise ValueError(f"unexpected sample rate {rate}")
    return audio


def context_prompt(path):
    """One line: 'Vocabulary: term, term, ...' (the format from the model card)."""
    terms = [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    return "World of Warcraft chat. Vocabulary: " + ", ".join(terms) + "."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--names", help="term list for the context prompt")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dtype", default="float32", choices=["float32", "bfloat16", "float16"])
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--set", default="", help="test set: recordings-SET/ -> results-SET/")
    args = parser.parse_args()

    meta_file = LAB / (f"recordings-{args.set}" if args.set else "recordings") / "meta.json"
    results_dir = LAB / (f"results-{args.set}" if args.set else "results")
    torch.set_num_threads(args.threads)
    logging.getLogger("transformers").setLevel(logging.ERROR)
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model, dtype=getattr(torch, args.dtype)).to(args.device).eval()
    prompt = context_prompt(args.names) if args.names else None

    def run(audio):
        inputs = processor.apply_transcription_request(
            audio=audio, language="English", prompt=prompt).to(model.device, model.dtype)
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
        new = out[:, inputs["input_ids"].shape[1]:]
        return processor.decode(new, return_format="transcription_only")[0].strip()

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    with torch.inference_mode():
        run(np.zeros(16000, dtype=np.float32))          # warm-up
        results, seconds = {}, {}
        for key, info in sorted(meta.items()):
            audio = load_audio(meta_file.parent / info["file"])
            start = time.perf_counter()
            text = run(audio)
            if args.device != "cpu":
                torch.cuda.synchronize()
            spent = time.perf_counter() - start
            results[key], seconds[key] = text, round(spent, 3)
            print(f"{key} {spent:5.2f}s  {text}", flush=True)
    results["_seconds"] = seconds
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {results_dir.name}/{args.run}.json")


if __name__ == "__main__":
    main()
