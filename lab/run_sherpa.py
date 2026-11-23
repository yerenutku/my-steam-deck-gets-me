#!/usr/bin/env python3
"""Transcribe every lab recording with a sherpa-onnx Parakeet model.

Usage (from ~/my-steam-deck-gets-me, after: source env.sh):
  envs/sherpa/bin/python lab/run_sherpa.py MODEL_DIR RUN_NAME [--beam] [--hotwords FILE] [--score N]
        [--threads N] [--split]

Writes lab/results/RUN_NAME.json: {"001": "text", ..., "_seconds": {"001": 0.41, ...}}
"_seconds" is the processing time per line (what you'd wait after releasing the button
when the whole recording is transcribed at once).
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
import soxr

LAB = Path(__file__).resolve().parent
META = LAB / "recordings" / "meta.json"
RESULTS = LAB / "results"
VAD_MODEL = LAB.parent / "models" / "silero_vad.onnx"


def pick(model_dir, stem):
    files = sorted(model_dir.glob(f"{stem}*.onnx"))
    int8 = [f for f in files if "int8" in f.name]
    return str((int8 or files)[0])


def load_audio(path):
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        audio = soxr.resample(audio, rate, 16000, quality="VHQ")
    return np.ascontiguousarray(audio, dtype=np.float32)


def make_recognizer(args):
    model_dir = Path(args.model)
    options = dict(
        encoder=pick(model_dir, "encoder"), decoder=pick(model_dir, "decoder"),
        joiner=pick(model_dir, "joiner"), tokens=str(model_dir / "tokens.txt"),
        num_threads=args.threads, sample_rate=16000, feature_dim=128,
        model_type="nemo_transducer",
        decoding_method="modified_beam_search" if (args.beam or args.hotwords) else "greedy_search",
    )
    if args.hotwords:
        # sherpa wants one phrase per line with no comments; the BPE vocab (bpe.vocab from the
        # model's .nemo tokenizer) lets it split names into the model's word pieces.
        terms = [l.strip() for l in Path(args.hotwords).read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        clean = LAB.parent / ".cache" / f"hotwords-{args.run}.txt"
        clean.parent.mkdir(exist_ok=True)
        clean.write_text("\n".join(terms) + "\n", encoding="utf-8")
        options.update(hotwords_file=str(clean), hotwords_score=args.score,
                       modeling_unit="bpe", bpe_vocab=args.bpe_vocab, max_active_paths=args.paths)
    elif args.beam:
        options.update(max_active_paths=args.paths)
    return sherpa_onnx.OfflineRecognizer.from_transducer(**options)


def segments(audio):
    """Split at speech pauses with Silero VAD (simulates transcribing while you talk)."""
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(VAD_MODEL)
    config.silero_vad.min_silence_duration = 0.35
    config.silero_vad.min_speech_duration = 0.2
    config.silero_vad.threshold = 0.5
    config.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
    window = config.silero_vad.window_size
    pieces = []
    for start in range(0, len(audio), window):
        vad.accept_waveform(audio[start:start + window])
        while not vad.empty():
            pieces.append(np.array(vad.front.samples, dtype=np.float32))
            vad.pop()
    vad.flush()
    while not vad.empty():
        pieces.append(np.array(vad.front.samples, dtype=np.float32))
        vad.pop()
    return pieces or [audio]


def join(texts):
    """Join per-pause pieces: drop a piece's final period and lowercase the next start."""
    out = ""
    for text in (t.strip() for t in texts):
        if not text:
            continue
        if out:
            out = out.rstrip(".")
            if text[:1].isupper() and not text.split()[0].isupper() and text.split()[0] != "I":
                text = text[0].lower() + text[1:]
            out += " " + text
        else:
            out = text
    return out


def decode(recognizer, audio):
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, audio)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("run")
    parser.add_argument("--beam", action="store_true")
    parser.add_argument("--hotwords")
    parser.add_argument("--score", type=float, default=1.5)
    parser.add_argument("--bpe-vocab", help="bpe.vocab for --hotwords (models/tokenizers/...)")
    parser.add_argument("--paths", type=int, default=4, help="beam width (max_active_paths)")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--split", action="store_true",
                        help="transcribe per pause; time = only the LAST piece (the wait after release)")
    parser.add_argument("--set", default="", help="test set: recordings-SET/ -> results-SET/")
    args = parser.parse_args()
    global META, RESULTS
    if args.set:
        META = LAB / f"recordings-{args.set}" / "meta.json"
        RESULTS = LAB / f"results-{args.set}"

    meta = json.loads(META.read_text(encoding="utf-8"))
    recognizer = make_recognizer(args)
    decode(recognizer, np.zeros(16000, dtype=np.float32))     # warm-up
    results, seconds = {}, {}
    for key, info in sorted(meta.items()):
        audio = load_audio(META.parent / info["file"])
        if args.split:
            texts, last = [], 0.0
            for piece in segments(audio):
                start = time.perf_counter()
                texts.append(decode(recognizer, piece))
                last = time.perf_counter() - start
            text, spent = join(texts), last
        else:
            start = time.perf_counter()
            text = decode(recognizer, audio)
            spent = time.perf_counter() - start
        results[key], seconds[key] = text, round(spent, 3)
        print(f"{key} {spent:5.2f}s  {text}", flush=True)
    results["_seconds"] = seconds
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.run}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"saved {RESULTS.name}/{args.run}.json")


if __name__ == "__main__":
    main()
