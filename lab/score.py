#!/usr/bin/env python3
"""Score transcription runs against the test lines.

Each run is results/<run-name>.json: {"001": "transcribed text", ...}
Prints, per run: word error rate (WER), exact-match rate, name/term hit rate,
and average processing time if the run file has a "_seconds" entry per line.

Usage: python3 score.py [-v RUN] [--names FILE] [--only TEXT] [--set NAME]
  -v RUN        also list every mistake of one run
  --names FILE  term list for the names/false-hit columns (default names.txt); use the list the
                run was boosted with, e.g. names-big.txt
  --only TEXT   only runs whose name contains TEXT
Columns: names = said terms that came out right; false = terms from the list written although
not said (wrongly inserted by boosting).
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = HERE / "recordings" / "meta.json"
RESULTS = HERE / "results"
NAMES = HERE / "names.txt"

NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def normalize(text):
    """Lowercase words without punctuation; number words -> digits; 'L F M' -> 'lfm'."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"[-_/]", " ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    words = [w.strip("'") for w in text.split()]
    words = [w for w in words if w]
    out = []
    i = 0
    while i < len(words):                      # twenty five -> 25
        w = words[i]
        if w in NUMBERS:
            value = NUMBERS[w]
            if value >= 20 and value % 10 == 0 and i + 1 < len(words) and \
                    words[i + 1] in NUMBERS and NUMBERS[words[i + 1]] < 10:
                value += NUMBERS[words[i + 1]]
                i += 1
            out.append(str(value))
        else:
            out.append(w)
        i += 1
    return out


def tokens(text):
    """Normalized words, with spelled-out letter runs merged: 'l f 2 m' -> 'lf2m'."""
    result = []
    run = ""
    for w in normalize(text):
        if len(w) == 1 and w not in ("a", "i"):
            run += w
            continue
        if run:
            result.append(run)
            run = ""
        result.append(w)
    if run:
        result.append(run)
    return result


def edit_ops(ref, hyp):
    """Levenshtein alignment; returns (errors, list of (op, ref_word, hyp_word))."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                ops.append(("sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], ""))
            i -= 1
        else:
            ops.append(("ins", "", hyp[j - 1]))
            j -= 1
    return d[n][m], list(reversed(ops))


def load_names(path=NAMES):
    names, seen = [], set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and tuple(tokens(line)) not in seen:
            seen.add(tuple(tokens(line)))
            names.append(line)
    return names


def occurrences(hay, needle):
    k = len(needle)
    return sum(hay[i:i + k] == needle for i in range(len(hay) - k + 1))


def contains(hay, needle):
    return occurrences(hay, needle) > 0


def score_run(meta, run, names):
    words = errors = exact = 0
    name_total = name_hit = false_hits = 0
    seconds = []
    details = []
    for key, info in sorted(meta.items()):
        if key not in run:
            continue
        ref, hyp = tokens(info["text"]), tokens(run[key])
        err, ops = edit_ops(ref, hyp)
        words += len(ref)
        errors += err
        exact += err == 0
        missed, wrong = [], []
        for name in names:
            nt = tokens(name)
            extra = occurrences(hyp, nt) - occurrences(ref, nt) if nt else 0
            if extra > 0:
                false_hits += extra
                wrong.append(name)
            if nt and contains(ref, nt):
                name_total += 1
                if contains(hyp, nt):
                    name_hit += 1
                else:
                    missed.append(name)
        if isinstance(run.get("_seconds"), dict) and key in run["_seconds"]:
            seconds.append(run["_seconds"][key])
        if err:
            details.append((key, info["text"], run[key], ops, missed, wrong))
    count = sum(1 for k in meta if k in run)
    return {
        "lines": count, "wer": errors / words if words else 0.0,
        "exact": exact / count if count else 0.0,
        "names": (name_hit, name_total), "false": false_hits,
        "avg_seconds": sum(seconds) / len(seconds) if seconds else None,
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", dest="verbose", metavar="RUN")
    parser.add_argument("--names", default=str(NAMES))
    parser.add_argument("--only", default="")
    parser.add_argument("--set", default="", help="score recordings-SET/ against results-SET/")
    args = parser.parse_args()
    global META, RESULTS
    if args.set:
        META = HERE / f"recordings-{args.set}" / "meta.json"
        RESULTS = HERE / f"results-{args.set}"
    meta = json.loads(META.read_text(encoding="utf-8"))
    names = load_names(args.names)
    runs = [p for p in sorted(RESULTS.glob("*.json")) if args.only in p.stem] if RESULTS.exists() else []
    if not runs:
        print("No matching runs in results/.")
        return
    rows = []
    for path in runs:
        run = json.loads(path.read_text(encoding="utf-8"))
        rows.append((path.stem, score_run(meta, run, names)))
    rows.sort(key=lambda r: r[1]["wer"])
    print(f"terms from {Path(args.names).name}: {len(names)}")
    print(f"{'run':38} {'lines':>5} {'WER':>7} {'exact':>7} {'names':>9} {'false':>5} {'sec/line':>9}")
    for name, s in rows:
        hit, total = s["names"]
        sec = f"{s['avg_seconds']:.2f}" if s["avg_seconds"] is not None else "-"
        print(f"{name:38} {s['lines']:5} {s['wer']:7.1%} {s['exact']:7.0%} "
              f"{hit:4}/{total:<4} {s['false']:5} {sec:>9}")
    for name, s in rows:
        if name != args.verbose:
            continue
        print(f"\nMistakes in {name}:")
        for key, ref, hyp, ops, missed, wrong in s["details"]:
            print(f"\n {key}  said: {ref}\n       got:  {hyp}")
            print("       " + ", ".join(f"{o}:{r or '-'}→{h or '-'}" for o, r, h in ops))
            if missed:
                print(f"       missed terms: {', '.join(missed)}")
            if wrong:
                print(f"       WRONGLY INSERTED: {', '.join(wrong)}")


if __name__ == "__main__":
    main()
