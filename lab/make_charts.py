#!/usr/bin/env python3
"""Draw the report's charts (light + dark PNG each) into lab/charts/.

Accuracy numbers are scored live from results*/ with score.py (names-big.txt), so the charts always match the
tables. The FPS numbers are the summary of the in-game tests (2026-11-21, fps_analyze.py output); the per-frame
raw data of those tests is gone (the WowVoiceFPS addon keeps a rolling buffer).

Run: envs/nemo/bin/python lab/make_charts.py
Colours: the dataviz reference palette, slots 1-3 (validated for up to three series in light and dark).
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

import score

LAB = Path(__file__).resolve().parent
OUT = LAB / "charts"
NAMES = score.load_names(LAB / "names-big.txt")

THEMES = {
    "light": dict(surface="#fcfcfb", text="#0b0b0b", text2="#52514e", muted="#898781", grid="#e1e0d9",
                  axis="#c3c2b7", series=["#2a78d6", "#eb6834", "#1baf7a"]),
    "dark": dict(surface="#1a1a19", text="#f0efec", text2="#c3c2b7", muted="#898781", grid="#2c2c2a",
                 axis="#383835", series=["#3987e5", "#d95926", "#199e70"]),
}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})


def scored(set_name, run):
    meta_path = LAB / (f"recordings-{set_name}" if set_name else "recordings") / "meta.json"
    res = LAB / (f"results-{set_name}" if set_name else "results") / f"{run}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return score.score_run(meta, json.loads(res.read_text(encoding="utf-8")), NAMES)


def new_fig(t, w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    fig.patch.set_facecolor(t["surface"])
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.tick_params(colors=t["text2"], length=0)
    return fig, ax


def hbar(ax, y, value, height, color, surface):
    """Horizontal bar: square at the baseline, 4 px-ish rounded data end, 2 px surface gap around it."""
    fig = ax.figure
    fig.canvas.draw()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    bbox = ax.get_window_extent()
    px_x = (x1 - x0) / bbox.width          # data units per pixel
    px_y = abs(y1 - y0) / bbox.height
    r = 4 * fig.dpi / 100 * px_x
    patch = FancyBboxPatch((0, y - height / 2), value, height, boxstyle=f"round,pad=0,rounding_size={r}",
                           mutation_aspect=px_y / px_x, facecolor=color, edgecolor="none", zorder=3)
    ax.add_patch(patch)
    ax.add_patch(Rectangle((0, y - height / 2), min(value, 2 * r), height, facecolor=color,
                           edgecolor="none", zorder=3))


def legend(ax, t, labels):
    handles = [Rectangle((0, 0), 1, 1, facecolor=c) for c in t["series"][:len(labels)]]
    leg = ax.figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.008, 0.875), ncol=len(labels),
                           frameon=False, fontsize=9, handlelength=1, handleheight=1, columnspacing=1.6)
    for txt in leg.get_texts():
        txt.set_color(t["text2"])


def title(fig, t, head, sub):
    fig.text(0.015, 0.975, head, ha="left", va="top", fontsize=13, fontweight="bold", color=t["text"])
    fig.text(0.015, 0.915, sub, ha="left", va="top", fontsize=9.5, color=t["text2"])


# 1. accuracy on the three test sets ---------------------------------------------------------------------------
SETUPS = [  # label, (lab run, fresh run, real run)
    ("My Steam Deck Gets Me\nParakeet on the GPU + names", ("tc-unified-gpu+fix", "tc-unified-gpu+fix", "ours-parakeet-gpu+fix")),
    ("Most accurate\nQwen3-ASR 1.7B on the GPU", ("tc-qwen17-gpu-ctx-big", "tc-qwen17-gpu-ctx", "ours-qwen-gpu-names")),
    ("NeMo on the CPU\nbeam search + name boosting", ("nemo-unified-beam4-big", "nemo-unified-beam4-big", "nemo-unified-beam4-names")),
    ("Decktation's setup\nParakeet v3 on the CPU", ("decktation-exact-v3-q8-cpu",) * 3),
    ("Voxpression's model\nWhisper base.en", ("vox-whisper-base-en", "vox-whisper-base-en", "voxpression-base-en")),
]
SETS = [("", "51 lab lines"), ("fresh", "28 fresh lines"), ("real", "14 real dictations")]


def chart_accuracy(t, mode):
    data = [[scored(s, runs[i])["wer"] * 100 for i, (s, _) in enumerate(SETS)] for _, runs in SETUPS]
    fig, ax = new_fig(t, 8.2, 5.6)
    fig.subplots_adjust(left=0.29, right=0.97, top=0.79, bottom=0.08)
    n = len(SETUPS)
    ax.set_ylim(n - 0.5, -0.6)
    ax.set_xlim(0, 36)
    ax.set_yticks(range(n))
    ax.set_yticklabels([s[0] for s in SETUPS], color=t["text"], fontsize=9.5)
    ax.get_yticklabels()[0].set_fontweight("bold")
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(range(0, 36, 5))
    ax.set_xticklabels([f"{v} %" for v in range(0, 36, 5)])
    h = 0.22
    for row, values in enumerate(data):
        for k, v in enumerate(values):
            y = row + (k - 1) * (h + 0.04)
            hbar(ax, y, v, h, t["series"][k], t["surface"])
            ax.text(v + 0.4, y, f"{v:.1f}", va="center", fontsize=8, color=t["text2"], zorder=4)
    legend(ax, t, [s[1] for s in SETS])
    title(fig, t, "Word error rate by test set (lower is better)",
          "Same recordings and scoring for every setup. Names list: 245 terms, 200 of them never said.")
    fig.savefig(OUT / f"accuracy-{mode}.png", facecolor=t["surface"])
    plt.close(fig)


# 2. accuracy vs speed (fresh set) -----------------------------------------------------------------------------
POINTS = [  # run, label, group (0 = ours shipped, 1 = existing tools, 2 = other setups we tested), label offset
    ("tc-unified-gpu+fix", "My Steam Deck Gets Me", 0, (8, -14)),
    ("tc-unified-gpu", "Parakeet GPU, no names", 2, (8, 2)),
    ("tc-qwen17-gpu-ctx", "Qwen3-ASR 1.7B, GPU", 2, (8, -4)),
    ("qwen17-names", "Qwen3-ASR 1.7B, CPU", 2, (-6, 8)),
    ("qwen06-names", "Qwen3-ASR 0.6B, CPU", 2, (8, 0)),
    ("nemo-unified-beam4-big", "NeMo + boosting, CPU", 2, (8, 6)),
    ("sh-unified-int8", "sherpa-onnx, no names", 2, (8, 0)),
    ("decktation-exact-v3-q8-cpu", "Decktation's setup", 1, (8, -2)),
    ("vox-whisper-base-en", "Voxpression's model", 1, (8, 0)),
    ("vox-whisper-base-en-names", "Voxpression's model + names", 1, (8, -10)),
]
GROUPS = ["My Steam Deck Gets Me", "Existing tools", "Other setups tested"]


def chart_speed(t, mode):
    fig, ax = new_fig(t, 8.2, 5.4)
    fig.subplots_adjust(left=0.09, right=0.97, top=0.79, bottom=0.14)
    ax.set_xscale("log")
    ax.set_xlim(0.18, 50)
    ax.set_ylim(0, 23)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(t["axis"])
    ax.grid(True, which="major", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ticks = [0.25, 0.5, 1, 2, 5, 10, 25]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{v:g} s" for v in ticks])
    ax.minorticks_off()
    ax.set_yticks(range(0, 24, 5))
    ax.set_yticklabels([f"{v} %" for v in range(0, 24, 5)])
    ax.set_xlabel("Compute time per line (log scale, model loaded, WoW closed*)", color=t["text2"], fontsize=9)
    ax.set_ylabel("Word error rate, 28 fresh lines", color=t["text2"], fontsize=9)
    for run, label, g, (dx, dy) in POINTS:
        s = scored("fresh", run)
        x, y = s["avg_seconds"], s["wer"] * 100
        ax.scatter([x], [y], s=80 if g == 0 else 55, color=t["series"][g], edgecolor=t["surface"],
                   linewidth=2, zorder=4)
        ax.annotate(label, (x, y), xytext=(dx, dy), textcoords="offset points", va="center",
                    ha="left" if dx >= 0 else "right", fontsize=8.5,
                    color=t["text"] if g == 0 else t["text2"], fontweight="bold" if g == 0 else "normal")
    legend(ax, t, GROUPS)
    fig.text(0.015, 0.015, "* Voxpression's model was timed with WoW running. Lower left is best.",
             fontsize=8, color=t["muted"])
    title(fig, t, "Accuracy vs. speed", "Every point is one setup on the same 28 fresh recordings.")
    fig.savefig(OUT / f"speed-{mode}.png", facecolor=t["surface"])
    plt.close(fig)


# 3. WoW's frame rate while transcribing (in-game test summary, 2026-11-21) ------------------------------------
FPS = [  # label, fps normally, fps while transcribing, worst frame ms, transcription s
    ("NeMo, CPU, 245 names", 46, 35, 155, 9.7),
    ("Qwen, GPU, 245 names", 48, 42, 99, 11.0),
    ("Qwen, GPU, 46 names", 51, 40, 70, 4.2),
    ("NeMo, CPU, 245 names", 30, 17, 180, 2.4),
    ("Qwen, GPU, 245 names", 30, 30, 37, 6.0),
    ("Qwen, GPU, 46 names", 30, 30, 40, 2.7),
]


def chart_fps(t, mode):
    fig, ax = new_fig(t, 8.2, 5.6)
    fig.subplots_adjust(left=0.24, right=0.80, top=0.79, bottom=0.09)
    rows = [0, 1, 2, 3.6, 4.6, 5.6]
    ax.set_ylim(6.1, -1.0)
    ax.set_xlim(0, 60)
    ax.set_yticks(rows)
    ax.set_yticklabels([f[0] for f in FPS], color=t["text"], fontsize=9.5)
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(range(0, 61, 10))
    ax.set_xticklabels([f"{v}" for v in range(0, 61, 10)])
    ax.set_xlabel("WoW frames per second", color=t["text2"], fontsize=9)
    h = 0.3
    for y, (label, idle, busy, worst, secs) in zip(rows, FPS):
        for k, v in enumerate((idle, busy)):
            yy = y + (k - 0.5) * (h + 0.04)
            hbar(ax, yy, v, h, t["series"][k], t["surface"])
            ax.text(v + 0.6, yy, f"{v}", va="center", fontsize=8, color=t["text2"], zorder=4)
        ax.text(61.5, y, f"worst frame {worst} ms\nwait {secs:g} s", va="center", fontsize=8,
                color=t["text"] if worst >= 150 else t["text2"],
                fontweight="bold" if worst >= 150 else "normal", clip_on=False)
    for y, text in ((-0.65, "WoW uncapped"), (2.95, "WoW capped at 30 FPS")):
        ax.text(0.5, y, text, ha="left", va="center", fontsize=9, fontweight="bold", color=t["text2"])
    legend(ax, t, ["Normally", "While transcribing"])
    title(fig, t, "WoW's frame rate while transcribing",
          "Steam Deck OLED, standing in a zone. The shipped engine (Parakeet, GPU) measured live: 52–58 FPS uncapped.")
    fig.savefig(OUT / f"fps-{mode}.png", facecolor=t["surface"])
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for mode, t in THEMES.items():
        chart_accuracy(t, mode)
        chart_speed(t, mode)
        chart_fps(t, mode)
    print("charts in", OUT)
