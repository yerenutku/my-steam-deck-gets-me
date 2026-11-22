#!/usr/bin/env python3
"""Apply service/namefix.py to existing result files and save them as RUN+fix, so score.py compares.

Usage: python3 lab/namefix_eval.py RUN --names FILE [--set NAME] [-v]
"""

import argparse
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB.parent / "service"))
from namefix import NameFixer  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("--names", required=True)
    p.add_argument("--set", default="")
    p.add_argument("-v", action="store_true")
    a = p.parse_args()
    rdir = LAB / (f"results-{a.set}" if a.set else "results")
    meta = json.loads((LAB / (f"recordings-{a.set}" if a.set else "recordings") / "meta.json").read_text())
    terms = [l.strip() for l in Path(a.names).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    fixer = NameFixer(terms)
    run = json.loads((rdir / f"{a.run}.json").read_text())
    out = {}
    for k, v in run.items():
        if k.startswith("_"):
            out[k] = v
            continue
        fixed, changes = fixer.fix(v)
        out[k] = fixed
        if changes and a.v:
            print(f"{k}: {changes}   said: {meta[k]['text']}")
    (rdir / f"{a.run}+fix.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
