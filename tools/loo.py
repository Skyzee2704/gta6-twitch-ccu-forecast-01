"""Leave-one-out validation over the 38 comparables in p00.in.

For each comparable with a valid hour-1 print, build a pseudo-case:
  known      = its own hour-1 print
  comparables = the other 37
  answers    = its actual hours 2..24
Run the forecaster on the pseudo-case and score it with tools/scorer.py.

Reports the mean pinball loss, typical miss, 90% coverage, and the full
per-case distribution (worst case first) -- one catastrophic pseudo-case is
a structural-failure signal, so the mean alone is not enough.

Tuning knobs are swept WITHOUT editing main.py: the harness monkey-patches
main.py's module-level tunables before forecasting:
  --spread MULT   global spread multiplier
  --k N           k-nearest neighbours
  --reg-min N     minimum valid comparables for the regression component
  --no-guards     disable the guard rails (ablation)
  --only IDX      only run pseudo-case #IDX (0-based, by comparable order)

Usage: python3 tools/loo.py [--spread 1.0] [--k 8] [--reg-min 8] [--no-guards]
"""
import argparse
import importlib.util
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from scorer import score  # noqa: E402


def load_main():
    spec = importlib.util.spec_from_file_location("forecast_main", REPO / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_ts(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def comp_hours(comp):
    """Map hour (1..24, relative to the comparable's day_start) -> viewers."""
    ds = parse_ts(comp["day_start"])
    out = {}
    for pt in comp["hourly"]:
        try:
            when = parse_ts(pt["from"])
        except (KeyError, ValueError):
            continue
        delta = (when - ds).total_seconds() / 3600.0
        h = int(round(delta)) + 1
        if 1 <= h <= 24 and pt.get("viewers") is not None and pt["viewers"] > 0:
            out[h] = float(pt["viewers"])
    return out


def comp_history(comp):
    """The comparable's own pre-release hourly points (48h before day_start),
    in the shape of a real case's history_hourly -- so target_baseline and
    target_premax see the same input the real case gives them."""
    ds = parse_ts(comp["day_start"])
    start = ds - timedelta(hours=48)
    out = []
    for pt in comp.get("hourly") or []:
        try:
            when = parse_ts(pt["from"])
        except (KeyError, ValueError):
            continue
        if start <= when < ds and pt.get("viewers") is not None:
            out.append({
                "from": pt["from"],
                "until": pt.get("until") or pt["from"],
                "viewers": pt["viewers"],
                "channels": pt.get("channels"),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spread", type=float, default=None)
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--reg-min", type=int, default=None)
    ap.add_argument("--no-guards", action="store_true")
    ap.add_argument("--only", type=int, default=None)
    args = ap.parse_args()

    main = load_main()
    if args.spread is not None:
        main.SPREAD_MULTIPLIER = args.spread
    if args.k is not None:
        main.K_NEIGHBORS = args.k
    if args.reg_min is not None:
        main.REG_MIN_N = args.reg_min
    if args.no_guards:
        main.APPLY_GUARDS = False

    case = json.loads(
        (REPO.parent / "kit/gta6-twitch-ccu-forecast-01-kit/input/p00.in")
        .read_text(encoding="utf-8")
    )
    comps = case["comparables"]
    levels = case["levels"]
    results = []
    skipped = []
    for idx, target in enumerate(comps):
        if args.only is not None and idx != args.only:
            continue
        hours = comp_hours(target)
        if 1 not in hours or not all(h in hours for h in range(2, 25)):
            skipped.append(target["name"])
            continue
        pseudo = {
            "id": f"loo-{idx}",
            "game": {"name": target["name"], "platforms": target.get("platforms")},
            "day_start": target["day_start"],
            "checkpoint": target["day_start"],
            "levels": levels,
            "known": [{
                "hour": 1, "from": target["day_start"], "until": target["day_start"],
                "viewers": hours[1], "channels": None, "reads": 1,
            }],
            "forecast": [{"hour": h} for h in range(2, 25)],
            "history": [],
            "history_hourly": comp_history(target),
            "streams": None,
            "categories_hourly": None,
            "comparables": [c for j, c in enumerate(comps) if j != idx],
            "notes": "",
        }
        forecast = main._forecast_case(pseudo)
        answers = {h: hours[h] for h in range(2, 25)}
        r = score(forecast, answers)
        results.append((target["name"], hours[1], r))
        print(f"[{idx:2d}] {target['name']:<42s} h1={hours[1]:>8.0f} "
              f"loss={r['loss']:.6f} miss={r['typical_miss_pct']:6.2f}% "
              f"cov90={r['coverage_90']:.3f}")
    losses = [r["loss"] for _, _, r in results]
    misses = [r["typical_miss_pct"] for _, _, r in results]
    covs = [r["coverage_90"] for _, _, r in results]
    print()
    print(f"LOO n={len(results)} skipped={skipped}")
    print(f"  mean loss   = {statistics.mean(losses):.6f} "
          f"(target: clearly < 0.387; no case > 0.5)")
    print(f"  median loss = {statistics.median(losses):.6f}")
    print(f"  max loss    = {max(losses):.6f} "
          f"({max(results, key=lambda t: t[2]['loss'])[0]})")
    print(f"  min loss    = {min(losses):.6f}")
    print(f"  mean miss   = {statistics.mean(misses):.2f}%")
    print(f"  mean cov90  = {statistics.mean(covs):.3f} (target 0.85-0.95)")
    print(f"  cases > 0.5 = {sum(1 for x in losses if x > 0.5)}")
    print(f"  cases > 0.387 = {sum(1 for x in losses if x > 0.387)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
