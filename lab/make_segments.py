#!/usr/bin/env python3
"""Find speech pauses in every lab recording with Silero VAD and save them.

Usage (from ~/my-steam-deck-gets-me): envs/sherpa/bin/python lab/make_segments.py [--silence 0.35]
Writes lab/recordings/segments.json: {"001": [[start_s, end_s], ...], ...} (16 kHz timeline).
run_nemo.py --split uses it to transcribe phrase by phrase, as if done while you talk.
"""

import argparse
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
import run_sherpa  # noqa: E402  (reuses load_audio + VAD settings)

import sherpa_onnx  # noqa: E402


def find(audio, silence):
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(run_sherpa.VAD_MODEL)
    config.silero_vad.min_silence_duration = silence
    config.silero_vad.min_speech_duration = 0.2
    config.silero_vad.threshold = 0.5
    config.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
    window = config.silero_vad.window_size
    spans = []

    def drain():
        while not vad.empty():
            start = vad.front.start
            spans.append([round(start / 16000, 3), round((start + len(vad.front.samples)) / 16000, 3)])
            vad.pop()

    for i in range(0, len(audio), window):
        vad.accept_waveform(audio[i:i + window])
        drain()
    vad.flush()
    drain()
    return spans


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--silence", type=float, default=0.35)
    args = parser.parse_args()
    meta = json.loads((LAB / "recordings" / "meta.json").read_text(encoding="utf-8"))
    out = {}
    for key, info in sorted(meta.items()):
        audio = run_sherpa.load_audio(LAB / "recordings" / info["file"])
        out[key] = find(audio, args.silence)
        print(key, len(out[key]), out[key])
    (LAB / "recordings" / "segments.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    pieces = [len(v) for v in out.values()]
    print(f"saved segments.json: {sum(p > 1 for p in pieces)} of {len(pieces)} lines have pauses, "
          f"avg {sum(pieces) / len(pieces):.1f} pieces")


if __name__ == "__main__":
    main()
