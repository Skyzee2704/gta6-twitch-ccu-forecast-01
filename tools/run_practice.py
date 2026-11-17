"""Run main.py on the 4 practice cases and score it.

Runs the repo's main.py with MAKEFUN_INPUT_DIR pointing at the kit's input/
and MAKEFUN_OUTPUT_DIR at a scratch dir, then scores each .out against
tools/answers_practice.json (hours 2..24) with tools/scorer.py.

Usage: python3 tools/run_practice.py [--main PATH] [--out DIR]
Prints per-case loss / typical miss / coverage, and the mean loss.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from scorer import check_format, score  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default=str(REPO / "main.py"))
    ap.add_argument("--out", default=str(HERE / "out_practice"))
    args = ap.parse_args()
    kit_input = (
        REPO.parent / "kit/gta6-twitch-ccu-forecast-01-kit/input"
    )
    answers = json.loads((HERE / "answers_practice.json").read_text(encoding="utf-8"))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["MAKEFUN_INPUT_DIR"] = str(kit_input)
    env["MAKEFUN_OUTPUT_DIR"] = str(outdir)
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, args.main], env=env, capture_output=True, text=True
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        print("main.py FAILED:")
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return 1
    print(f"main.py ran 4 cases in {elapsed:.2f}s ({elapsed / 4:.2f}s/case)")
    losses = []
    for case_id in ["p00", "p01", "p02", "p03"]:
        outp = outdir / f"{case_id}.out"
        fc = json.loads(outp.read_text(encoding="utf-8"))
        problems = check_format(fc)
        size = outp.stat().st_size
        ans = {int(h): v for h, v in answers[case_id]["hours"].items() if int(h) >= 2}
        r = score(fc, ans)
        losses.append(r["loss"])
        print(
            f"{case_id} {answers[case_id]['game']:<28s} loss={r['loss']:.6f} "
            f"miss={r['typical_miss_pct']:6.2f}% cov90={r['coverage_90']:.3f} "
            f"bytes={size} fmt={'OK' if not problems else problems}"
        )
    print(f"MEAN practice loss = {sum(losses) / len(losses):.6f} "
          f"(target <= 0.13; house baseline ~0.387)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
