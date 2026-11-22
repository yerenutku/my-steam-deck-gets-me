#!/usr/bin/env python3
"""Transcribe every lab recording with an NVIDIA NeMo Parakeet model (full precision, CPU).

Usage (from ~/wowvoice, after: source env.sh):
  envs/nemo/bin/python lab/run_nemo.py MODEL RUN_NAME   (GPU: envs/gpu/bin/python ... --device cuda)
        [--beam N] [--boost FILE] [--alpha A] [--context-score S] [--threads N]

MODEL is a Hugging Face id (nvidia/parakeet-tdt-0.6b-v2) or a local .nemo path.
--boost FILE: phrase boosting with NeMo's boosting tree (one term per line, # = comment).
Writes lab/results/RUN_NAME.json like run_sherpa.py.
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
META = LAB / "recordings" / "meta.json"
RESULTS = LAB / "results"
SEGMENTS = LAB / "recordings" / "segments.json"
PAD_BEFORE, PAD_AFTER = 0.15, 0.15   # seconds kept around each speech span (--pad)


def join(texts):
    """Join per-pause pieces: drop a piece's final period and lowercase the next start."""
    out = ""
    for text in (t.strip() for t in texts):
        if not text:
            continue
        if out:
            out = out.rstrip(".")
            first = text.split()[0]
            if text[:1].isupper() and not first.isupper() and first != "I":
                text = text[0].lower() + text[1:]
            out += " " + text
        else:
            out = text
    return out


def load_audio(path):
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate == 48000:
        audio = resample_poly(audio, 1, 3).astype(np.float32)
    elif rate != 16000:
        raise ValueError(f"unexpected sample rate {rate}")
    return audio


def read_terms(path):
    terms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def configure(model, args):
    from omegaconf import OmegaConf, open_dict
    from nemo.collections.asr.parts.context_biasing.boosting_graph_batched import BoostingTreeModelConfig

    cfg = model.cfg.decoding
    boost = None
    if args.boost:
        boost = OmegaConf.structured(BoostingTreeModelConfig(
            key_phrases_list=read_terms(args.boost), context_score=args.context_score,
            depth_scaling=2.0, use_triton=False))
    with open_dict(cfg):
        if args.beam:
            cfg.strategy = "malsd_batch"
            cfg.beam.beam_size = args.beam
            if boost is not None:
                cfg.beam.boosting_tree = boost
                cfg.beam.boosting_tree_alpha = args.alpha
        else:
            cfg.strategy = "greedy_batch"
            if boost is not None:
                cfg.greedy.boosting_tree = boost
                cfg.greedy.boosting_tree_alpha = args.alpha
    model.change_decoding_strategy(cfg, verbose=False)


def text_of(hyp):
    # transcribe() returns [hyp] for greedy and [[best, 2nd, ...]] (N-best) for beam search
    while isinstance(hyp, (list, tuple)):
        hyp = hyp[0]
    return (hyp.text if hasattr(hyp, "text") else str(hyp)).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--beam", type=int, default=0)
    parser.add_argument("--boost")
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--context-score", type=float, default=1.0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--segments", choices=["trim", "split"],
                        help="use recordings/segments.json (make_segments.py): trim = cut silence "
                             "around speech; split = per pause, time = last piece only")
    parser.add_argument("--pad", type=float, nargs=2, default=[PAD_BEFORE, PAD_AFTER],
                        metavar=("BEFORE", "AFTER"), help="seconds kept around speech spans")
    parser.add_argument("--device", default="cpu", help="cpu or cuda (AMD ROCm GPU, needs envs/gpu)")
    parser.add_argument("--set", default="", help="test set: recordings-SET/ -> results-SET/")
    args = parser.parse_args()
    global META, RESULTS
    if args.set:
        META = LAB / f"recordings-{args.set}" / "meta.json"
        RESULTS = LAB / f"results-{args.set}"

    logging.getLogger("nemo_logger").setLevel(logging.ERROR)
    torch.set_num_threads(args.threads)
    from nemo.collections.asr.models import ASRModel

    if args.model.endswith(".nemo"):
        model = ASRModel.restore_from(args.model, map_location=args.device)
    else:
        model = ASRModel.from_pretrained(args.model, map_location=args.device)
    model.eval()
    configure(model, args)

    meta = json.loads(META.read_text(encoding="utf-8"))
    spans = json.loads(SEGMENTS.read_text(encoding="utf-8")) if args.segments else {}

    def run(audio):
        text = text_of(model.transcribe([audio], batch_size=1, verbose=False))
        if args.device != "cpu":
            torch.cuda.synchronize()
        return text

    with torch.inference_mode():
        run(np.zeros(16000, dtype=np.float32))   # warm-up
        results, seconds = {}, {}
        for key, info in sorted(meta.items()):
            audio = load_audio(META.parent / info["file"])
            pieces = [audio]
            if args.segments and spans.get(key):
                cut = lambda a, b: audio[max(0, int((a - args.pad[0]) * 16000)):int((b + args.pad[1]) * 16000)]
                if args.segments == "trim":
                    pieces = [cut(spans[key][0][0], spans[key][-1][1])]
                else:
                    pieces = [cut(a, b) for a, b in spans[key]]
            texts = []
            for piece in pieces:          # only the last piece is waited for after release
                start = time.perf_counter()
                texts.append(run(piece))
                spent = time.perf_counter() - start
            text = join(texts)
            results[key], seconds[key] = text, round(spent, 3)
            print(f"{key} {spent:5.2f}s  {text}", flush=True)
    results["_seconds"] = seconds
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {RESULTS.name}/{args.run}.json")


if __name__ == "__main__":
    main()
