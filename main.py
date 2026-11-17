"""gta6-twitch-ccu-forecast-01: quantile forecaster for GTA VI launch-day Twitch viewers.

Reads one case (schema makefun/twitch-ccu-case/v1) and writes, for hours 2..24
of the release day, five quantiles of that hour's concurrent Twitch viewers,
scored by pinball loss on the log scale.

Method: an ensemble of three voting components, all refit at runtime from
the comparables carried in the case file itself (never hardcoded research
tables), combined by per-quantile median, then held by ratio guards that are
also fit at runtime:
  A. log-log regression per hour (kernel-weighted, slope shrunk toward 1)
  B. pooled launch-shape (median ratio per hour-1 size band), bent by the
     midnight-unlock ramp whose amplitude is fit from console-only launches
  C. k-nearest comparable launches (weighted median of their ratio curves)
(The ramp refines the pooled shape; it is one vote with it, not a separate
vote -- counting it separately would double-weight the pooled shape.)
The anchor is hour 1's print only. Pre-release levels are a similarity
feature, never a level anchor. The `unlock` field of comparables is free
human text and is never parsed.

Standard library only, no network, deterministic (no randomness anywhere).
Runs as `python3 main.py` with $MAKEFUN_INPUT_DIR / $MAKEFUN_OUTPUT_DIR,
else /input and /output.
"""

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from statistics import NormalDist, median

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# ---- Tunables (chosen by leave-one-out measurement, see tools/loo.py) ----
SPREAD_MULTIPLIER = 1.0   # global multiplier on the final spread
K_NEIGHBORS = 6           # neighbours for the k-nearest component (tuned: 6 beats 8 and 12 on LOO)
REG_MIN_N = 8             # minimum valid comparables for component A to vote
APPLY_GUARDS = True       # ratio guards on the median curve
PLATFORM_PENALTY = 0.5    # similarity-distance penalty for a different platform class
BASELINE_WEIGHT = 0.5     # weight of the pre-release baseline term in the distance
SPREAD_FLOOR = 0.15       # final spread never narrower than this (log units)
SPREAD_CAP = 0.8          # final spread never wider than this (log units)
PEAK_FIT_MIN_HOUR1 = 100000.0  # peak-ratio guard is fit on launches this big or bigger
DIP_MARGIN = 0.02         # margin below the observed dip floor
UNLOCK_UNCERTAINTY = 0.15  # extra log-spread in the unlock window (hours 6..10)

_HOURS = list(range(2, 25))
_ND = NormalDist()
# Hour-1 size bands for the pooled shape: under 20k, 20k-100k, 100k-250k, 250k+.
_BAND_EDGES = [0.0, 20000.0, 100000.0, 250000.0, float("inf")]


def round2(x):
    """Round to 2 decimals, half up (same as the kit starter)."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value.is_integer() else value


def z_of(level):
    """Standard normal quantile at `level`, computed, never hardcoded."""
    return _ND.inv_cdf(level)


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def safe_log(v):
    """log(viewers), treating 0 / missing as 1 (RULES counts a print below 1 as 1)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return math.log(v) if v > 1.0 else 0.0


def percentile(sorted_vals, q):
    """q-th quantile of a sorted list, linear interpolation (deterministic)."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def weighted_quantile(pairs, q):
    """q-th weighted quantile of (value, weight) pairs: smallest value whose
    cumulative weight reaches q of the total. Deterministic, no interpolation."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return None
    target = q * total
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= target:
            return value
    return ordered[-1][0]


def comparable_hours(comp):
    """Hour (1..24, relative to the comparable's day_start) -> viewers.

    A point belongs to hour h when its `from` equals day_start + (h-1) hours.
    Missing points are skipped, never interpolated.
    """
    try:
        day_start = parse_ts(comp["day_start"])
    except (KeyError, ValueError):
        return {}
    out = {}
    for pt in comp.get("hourly") or []:
        try:
            when = parse_ts(pt["from"])
            viewers = float(pt["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        delta = (when - day_start).total_seconds() / 3600.0
        hour = int(round(delta)) + 1
        if 1 <= hour <= 24 and viewers > 0:
            out[hour] = viewers
    return out


def comparable_baseline(comp):
    """Mean viewers per hour in the 48h before the comparable's day_start.

    Returns None when no point falls in that window (feature missing).
    """
    try:
        day_start = parse_ts(comp["day_start"])
    except (KeyError, ValueError):
        return None
    start = day_start - timedelta(hours=48)
    total = 0.0
    count = 0
    for pt in comp.get("hourly") or []:
        try:
            when = parse_ts(pt["from"])
            viewers = float(pt["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= when < day_start and viewers >= 0:
            total += viewers
            count += 1
    if count == 0:
        return None
    return total / count


def is_console_only(comp):
    """Console-only launch (no PC in its platform list)."""
    return "PC" not in (comp.get("platforms") or "")


def target_hour1(case):
    """Hour-1 print, with the fallback chain from the design.

    1. `known` row with hour == 1; 2. last history_hourly point before the
    checkpoint; 3. 1. Never raises.
    """
    for row in case.get("known") or []:
        if row.get("hour") == 1:
            try:
                v = float(row["viewers"])
                if v > 0:
                    return v
            except (KeyError, TypeError, ValueError):
                pass
    hourly = case.get("history_hourly") or []
    if hourly:
        try:
            v = float(hourly[-1]["viewers"])
            if v > 0:
                return v
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    return 1.0


def target_baseline(case):
    """Mean viewers per hour in the 48h before the target's day_start.

    From history_hourly, falling back to history; None when unavailable.
    """
    try:
        day_start = parse_ts(case["day_start"])
    except (KeyError, ValueError):
        return None
    start = day_start - timedelta(hours=48)
    for key in ("history_hourly", "history"):
        rows = case.get(key) or []
        total = 0.0
        count = 0
        for pt in rows:
            try:
                when = parse_ts(pt.get("from") or pt.get("at"))
                viewers = float(pt["viewers"])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= when < day_start and viewers >= 0:
                total += viewers
                count += 1
        if count:
            return total / count
    return None


def target_is_console(case):
    """Platform class of the target launch. The case carries no platform
    field for the target; the competition's target (GTA VI) releases on
    PS5 + Xbox Series X|S only, no PC at launch (RULES), so it is console.
    A harness may pass the target's platforms in game.platforms instead."""
    platforms = (case.get("game") or {}).get("platforms")
    if platforms is None:
        return True
    return "PC" not in platforms


def band_of(hour1):
    """Index of the hour-1 size band containing `hour1`."""
    for i in range(len(_BAND_EDGES) - 1):
        if _BAND_EDGES[i] <= hour1 < _BAND_EDGES[i + 1]:
            return i
    return len(_BAND_EDGES) - 2


def persistence_quantiles(p1, hour, levels):
    """House-baseline forecast: every hour stays at hour 1's print, spread
    widening like a random walk in log space (starter formula)."""
    spread = 0.15 * math.sqrt(hour - 1)
    return [round2(p1 * math.exp(z_of(tau) * spread)) for tau in levels]


def quantiles_from(med, spread, levels):
    """Five quantiles around a median with a log spread, rounded half-up."""
    out = []
    for tau in levels:
        q = med * math.exp(z_of(tau) * spread)
        out.append(round2(max(0.01, min(1_000_000_000.0, q))))
    # Rounding is monotone, but enforce non-decreasing explicitly.
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def _prepare(case, p1):
    """Extract per-comparable features once: hour map, hour-1, baseline,
    platform class, and the kernel similarity weight to the target.

    Returns a list of dicts sorted by name (deterministic order).
    """
    base_t = target_baseline(case)
    console_t = target_is_console(case)
    log_p1 = safe_log(p1)
    log_base_t = safe_log(base_t) if base_t is not None else None
    rows = []
    for comp in case.get("comparables") or []:
        hours = comparable_hours(comp)
        if 1 not in hours:
            continue
        rows.append({
            "name": comp.get("name") or "",
            "hours": hours,
            "hour1": hours[1],
            "baseline": comparable_baseline(comp),
            "console": is_console_only(comp),
        })
    # Baseline-distance term: comparables missing a baseline get the mean
    # contribution of the ones that have it (a neutral weight for that feature).
    base_terms = []
    for row in rows:
        if base_t is not None and row["baseline"] is not None:
            base_terms.append(abs(log_base_t - safe_log(row["baseline"])))
    mean_base_term = sum(base_terms) / len(base_terms) if base_terms else 0.0
    for row in rows:
        dist = abs(log_p1 - safe_log(row["hour1"]))
        if base_t is not None and row["baseline"] is not None:
            dist += BASELINE_WEIGHT * abs(log_base_t - safe_log(row["baseline"]))
        elif base_t is not None:
            dist += BASELINE_WEIGHT * mean_base_term
        if row["console"] != console_t:
            dist += PLATFORM_PENALTY
        row["distance"] = dist
        row["weight"] = math.exp(-dist)
    rows.sort(key=lambda r: r["name"])
    return rows


def _band_curves(rows):
    """Per band and hour: (median ratio to hour 1, log-spread from IQR).

    A band with fewer than 5 valid comparables for an hour borrows the band
    below it for that hour, so the median never rests on two or three points.
    Returns {band: {hour: (median_ratio, spread)}}.
    """
    curves = {}
    for band in range(len(_BAND_EDGES) - 1):
        curves[band] = {}
        for hour in _HOURS:
            ratios = []
            use_band = band
            while use_band >= 0:
                ratios = [
                    r["hours"][hour] / r["hour1"]
                    for r in rows
                    if band_of(r["hour1"]) == use_band
                    and hour in r["hours"]
                ]
                if len(ratios) >= 5 or use_band == 0:
                    break
                use_band -= 1
                # merge the band below: collect from all bands down to it
                ratios = [
                    r["hours"][hour] / r["hour1"]
                    for r in rows
                    if band_of(r["hour1"]) <= band and band_of(r["hour1"]) >= use_band
                    and hour in r["hours"]
                ]
                if len(ratios) >= 5:
                    break
            if not ratios:
                ratios = [
                    r["hours"][hour] / r["hour1"]
                    for r in rows if hour in r["hours"]
                ]
            if not ratios:
                continue
            log_ratios = sorted(safe_log(v) for v in ratios)
            med_ratio = median(ratios)
            q25 = percentile(log_ratios, 0.25)
            q75 = percentile(log_ratios, 0.75)
            spread = max(SPREAD_FLOOR, (q75 - q25) / 1.349)
            curves[band][hour] = (med_ratio, spread)
    return curves


def _regression(rows, p1, hour):
    """Component A: weighted log-log regression of hour-h viewers on hour-1
    viewers, slope shrunk toward 1. Returns (median, spread) or None."""
    pts = [(r, r["hours"][hour]) for r in rows if hour in r["hours"]]
    if len(pts) < REG_MIN_N:
        return None
    xs = [safe_log(r["hour1"]) for r, _ in pts]
    ys = [safe_log(v) for _, v in pts]
    ws = [r["weight"] for r, _ in pts]
    sw = sum(ws)
    if sw <= 0:
        return None
    xbar = sum(w * x for w, x in zip(ws, xs)) / sw
    ybar = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - xbar) ** 2 for w, x in zip(ws, xs))
    if sxx <= 0:
        return None
    sxy = sum(w * (x - xbar) * (y - ybar) for w, x, y in zip(ws, xs, ys))
    slope = sxy / sxx
    neff = sw * sw / sum(w * w for w in ws)
    slope_s = 1.0 + (slope - 1.0) * neff / (neff + 5.0)
    intercept = ybar - slope_s * xbar
    med = math.exp(intercept + slope_s * safe_log(p1))
    var = sum(w * (y - (intercept + slope_s * x)) ** 2
              for w, x, y in zip(ws, xs, ys)) / sw
    spread = max(SPREAD_FLOOR, math.sqrt(var))
    return med, spread


def _knn(rows, p1, hour):
    """Component D: weighted median ratio curve of the K nearest launches.
    Returns (median, spread) or None."""
    near = sorted(rows, key=lambda r: (r["distance"], r["name"]))[:K_NEIGHBORS]
    pts = [(r["hours"][hour] / r["hour1"], r["weight"])
           for r in near if hour in r["hours"]]
    if len(pts) < 3:
        return None
    med_ratio = weighted_quantile(pts, 0.5)
    log_pts = [(safe_log(v), w) for v, w in pts]
    q25 = weighted_quantile(log_pts, 0.25)
    q75 = weighted_quantile(log_pts, 0.75)
    spread = max(SPREAD_FLOOR, (q75 - q25) / 1.349)
    return p1 * med_ratio, spread


def _ramp_amplitude(rows, curves):
    """Fit the unlock-wave amplitude from console-only comparables: the
    median morning excess growth (log hour 5 -> 12) above the pooled shape
    of each launch's own band. 0 when too few console launches qualify."""
    excess = []
    for r in rows:
        if not r["console"]:
            continue
        hours = r["hours"]
        if 5 not in hours or 12 not in hours:
            continue
        band = band_of(r["hour1"])
        if 5 not in curves[band] or 12 not in curves[band]:
            continue
        pooled_growth = math.log(curves[band][12][0]) - math.log(curves[band][5][0])
        actual_growth = safe_log(hours[12]) - safe_log(hours[5])
        excess.append(actual_growth - pooled_growth)
    if len(excess) < 3:
        return 0.0
    return median(excess)


def _wave(hour):
    """Unlock-wave shape: 0 before hour 5, smooth rise over hours 6..10,
    flat after (viewers who unlocked stay watching)."""
    if hour <= 5:
        return 0.0
    if hour >= 10:
        return 1.0
    return (1.0 - math.cos(math.pi * (hour - 5) / 5.0)) / 2.0


def _peak_guard(rows, p1):
    """Peak-ratio guard, fit at runtime on launches with hour-1 >= 100k
    (the size regime the guard is for; the all-launch fit extrapolates
    absurdly low at giant scale -- see validation notes). Returns
    (lower, upper) allowed peak ratio, or None when the fit is unsupported
    or the target is below the fit regime."""
    if p1 < PEAK_FIT_MIN_HOUR1:
        return None
    pts = []
    for r in rows:
        if r["hour1"] < PEAK_FIT_MIN_HOUR1:
            continue
        peak = max(r["hours"][h] for h in _HOURS if h in r["hours"])
        pts.append((safe_log(r["hour1"]), safe_log(peak / r["hour1"])))
    if len(pts) < 8:
        return None
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
    intercept = my - slope * mx
    resid = [y - (intercept + slope * x) for x, y in pts]
    sd = math.sqrt(sum(v * v for v in resid) / len(resid))
    top = max(x for x, _ in pts)
    at = min(safe_log(p1), top)
    fit = intercept + slope * at
    return math.exp(fit - sd), math.exp(fit + sd)


def _dip_floor(rows):
    """Lowest morning dip (min ratio hours 9..11) among launches with
    hour-1 > 100k, minus a small margin. None when no such launch exists."""
    dips = []
    for r in rows:
        if r["hour1"] <= PEAK_FIT_MIN_HOUR1:
            continue
        vals = [r["hours"][h] / r["hour1"] for h in (9, 10, 11) if h in r["hours"]]
        if vals:
            dips.append(min(vals))
    if not dips:
        return None
    return min(dips) - DIP_MARGIN


def forecast_case(case, name):
    """Forecast one case. Never raises: on any failure it falls back to the
    persistence baseline so the output is always a valid forecast."""
    try:
        return _forecast_case(case)
    except Exception:
        levels = case.get("levels") or [0.05, 0.25, 0.5, 0.75, 0.95]
        p1 = max(1.0, target_hour1(case))
        hours = []
        for row in case.get("forecast") or [{"hour": h} for h in _HOURS]:
            h = row["hour"]
            hours.append({"hour": h, "q": persistence_quantiles(p1, h, levels)})
        return {"hours": hours}


def _forecast_case(case):
    levels = case.get("levels") or [0.05, 0.25, 0.5, 0.75, 0.95]
    med_idx = levels.index(0.5) if 0.5 in levels else len(levels) // 2
    p1 = max(1.0, target_hour1(case))
    rows = _prepare(case, p1)
    curves = _band_curves(rows)
    band = band_of(p1)
    amplitude = _ramp_amplitude(rows, curves)
    peak = _peak_guard(rows, p1) if APPLY_GUARDS else None
    dip = _dip_floor(rows) if APPLY_GUARDS else None

    medians = {}
    spreads = {}
    for hour in _HOURS:
        votes = []  # (median, spread) per component that votes this hour
        reg = _regression(rows, p1, hour)
        if reg is not None:
            votes.append(reg)
        if hour in curves[band]:
            # Pooled shape bent by the unlock wave is ONE component: the
            # ramp refines the pooled shape, it is not an independent model,
            # so it gets one vote, not two (counting it separately double-
            # weights the pooled shape in the median).
            ratio, spread_b = curves[band][hour]
            wave = _wave(hour)
            med_pb = p1 * ratio * math.exp(amplitude * wave)
            unc = UNLOCK_UNCERTAINTY if 6 <= hour <= 10 else 0.0
            spread_pb = math.sqrt(spread_b * spread_b + unc * unc)
            votes.append((med_pb, spread_pb))
        knn = _knn(rows, p1, hour)
        if knn is not None:
            votes.append(knn)
        if len(votes) < 2:
            medians[hour] = p1
            spreads[hour] = 0.15 * math.sqrt(hour - 1)
            continue
        # Per-quantile median across the voting components.
        combined = []
        for tau in levels:
            vals = [m * math.exp(z_of(tau) * s) for m, s in votes]
            combined.append(median(vals))
        medians[hour] = combined[med_idx]
        spreads[hour] = median([s for _, s in votes])

    if APPLY_GUARDS:
        # Peak-ratio guard: cap the median curve's peak, and lift a curve
        # whose peak falls below the allowed range (shape preserved).
        if peak is not None:
            lower, upper = peak
            for hour in _HOURS:
                ratio = medians[hour] / p1
                if ratio > upper:
                    medians[hour] = p1 * upper
            top = max(medians[h] / p1 for h in _HOURS)
            if top < lower:
                scale = lower / top
                for hour in _HOURS:
                    medians[hour] *= scale
        # Prime-time floor: hours 19..23 never forecast below hour 1.
        for hour in range(19, 24):
            if medians[hour] < p1:
                medians[hour] = p1
        # Morning-dip floor: hours 9..11 never below the observed dip floor.
        if dip is not None:
            for hour in (9, 10, 11):
                if medians[hour] / p1 < dip:
                    medians[hour] = p1 * dip

    hours_out = []
    for row in case.get("forecast") or [{"hour": h} for h in _HOURS]:
        h = row["hour"]
        spread = min(SPREAD_CAP, max(SPREAD_FLOOR,
                                       spreads[h] * SPREAD_MULTIPLIER))
        hours_out.append({"hour": h,
                          "q": quantiles_from(medians[h], spread, levels)})
    return {"hours": hours_out}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
