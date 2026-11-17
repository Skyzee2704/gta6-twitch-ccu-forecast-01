"""Local scorer for gta6-twitch-ccu-forecast-01.

Implements the pinball loss exactly as RULES.txt defines it, so local
numbers mean the same as the grader's:

  d        = ln(y) - ln(q)          (y = hour print, q = quantile; y < 1 counts as 1)
  item     = 2 * max(tau * d, (tau - 1) * d)
  loss     = mean of item over every scored hour and level

Also reports the two informational figures from RULES:
  typical miss (%) = 100 * (exp(mean |ln(y) - ln(q50)|) - 1)
  90% coverage     = share of scored hours with q05 <= y <= q95

Usage:
  python3 tools/scorer.py <forecast.json> <answers.json>
where answers.json maps hour (as string) -> print (number), e.g.
{"2": 19397.0, "3": 20292.0, ...}. Exit 0 and prints one JSON line.
"""
import json
import math
import sys

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


def pinball(y, q, tau):
    """One pinball item, log scale. y < 1 counts as 1 (RULES)."""
    y = max(1.0, float(y))
    q = float(q)
    if q <= 0:
        raise ValueError("quantile must be > 0")
    d = math.log(y) - math.log(q)
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def score(forecast, answers):
    """forecast: {"hours": [{"hour": h, "q": [5 numbers]}]}.
    answers: {hour: print}. Returns dict with loss, typical_miss_pct,
    coverage_90, n_items, n_hours."""
    items = []
    abs_med = []
    covered = 0
    scored_hours = 0
    for row in forecast["hours"]:
        h = row["hour"]
        if h not in answers:
            continue
        y = answers[h]
        qs = row["q"]
        if len(qs) != 5:
            raise ValueError(f"hour {h}: expected 5 quantiles, got {len(qs)}")
        for tau, q in zip(LEVELS, qs):
            items.append(pinball(y, q, tau))
        abs_med.append(abs(math.log(max(1.0, float(y))) - math.log(float(qs[2]))))
        if qs[0] <= y <= qs[4]:
            covered += 1
        scored_hours += 1
    if not items:
        raise ValueError("no scored hours (no overlap between forecast and answers)")
    return {
        "loss": sum(items) / len(items),
        "typical_miss_pct": 100.0 * (math.exp(sum(abs_med) / len(abs_med)) - 1.0),
        "coverage_90": covered / scored_hours,
        "n_items": len(items),
        "n_hours": scored_hours,
    }


def check_format(forecast):
    """Return a list of format problems (empty = valid per RULES)."""
    problems = []
    hours = forecast.get("hours")
    if not isinstance(hours, list) or len(hours) != 23:
        problems.append(f"expected 23 rows, got {len(hours) if isinstance(hours, list) else 'non-list'}")
        return problems
    seen = set()
    for row in hours:
        h = row.get("hour")
        if h in seen:
            problems.append(f"duplicate hour {h}")
        seen.add(h)
        if h < 2 or h > 24:
            problems.append(f"hour out of range: {h}")
        qs = row.get("q")
        if not isinstance(qs, list) or len(qs) != 5:
            problems.append(f"hour {h}: expected 5 quantiles")
            continue
        for q in qs:
            if not isinstance(q, (int, float)) or isinstance(q, bool):
                problems.append(f"hour {h}: non-numeric quantile {q!r}")
            elif not math.isfinite(q) or q <= 0 or q > 1_000_000_000:
                problems.append(f"hour {h}: quantile out of (0, 1e9]: {q}")
        if all(isinstance(q, (int, float)) and math.isfinite(q) for q in qs):
            for a, b in zip(qs, qs[1:]):
                if b < a:
                    problems.append(f"hour {h}: quantiles decrease ({qs})")
                    break
    if seen != set(range(2, 25)):
        problems.append(f"hours are not exactly 2..24: {sorted(seen)}")
    return problems


def main():
    if len(sys.argv) != 3:
        print("usage: scorer.py <forecast.json> <answers.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        forecast = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        raw_answers = json.load(f)
    answers = {int(h): float(v) for h, v in raw_answers.items()}
    problems = check_format(forecast)
    result = score(forecast, answers)
    result["format_problems"] = problems
    print(json.dumps(result, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
