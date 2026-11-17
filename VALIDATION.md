# Validation — gta6-twitch-ccu-forecast-01

All numbers measured in-session (2026-11-18), by data. No invented figures.
Scorer verified against the RULES worked example: loss 0.112545, miss 19.52%,
coverage 1.0 — exact match.

## Model (final)
- Ensemble of 3 voting components, per-quantile median: (A) log-log regression
  per hour (kernel-weighted, slope shrunk toward 1), (B) pooled launch-shape
  per hour-1 band bent by the midnight-unlock ramp (one vote — the ramp
  refines the pooled shape, it is not a separate vote), (C) k-nearest
  (k=6, tuned: 6 beats 8 and 12 on LOO). Guards (peak-ratio, prime-time
  floor, morning-dip floor) fit at runtime from the comparables.
- SPREAD_MULTIPLIER = 1.0 (kept: optimal for the final's regime, see below).
- REG_MIN_N = 8 (never binds in practice — always >=12 valid comparables).

## Practice (4 cases, SullyGnome "Average viewers" answers)
| case | loss | typical miss | cov90 |
|---|---|---|---|
| p00 Wolverine | 0.3748 | 84.82% | 0.609 |
| p01 RDR2 | 0.2017 | 40.43% | 0.783 |
| p02 GoW Ragnarok | 0.1546 | 27.56% | 0.696 |
| p03 Spider-Man 2 | 0.1952 | 30.28% | 0.739 |
| **MEAN** | **0.2316** | | |
House baseline (persistence) = 0.3871. Model beats it by 40%.
Design target was <=0.13 — **NOT met**. The gap is Wolverine (0.375):
its 9.09x peak is far steeper than the 20-100k band median (2.4x).

## LOO over 37 comparables (GTA VI pre-release comparable skipped: no hour-1)
- mean 0.4168, median 0.2953, max 1.7735 (Marathon), min 0.0686
- mean miss 108.51%, mean cov90 0.678, 9 cases >0.5, 11 cases >0.387
- Baseline (persistence) LOO mean = 0.9296 — model is 55% better.
- Design targets (mean clearly <0.387, no case >0.5, cov 0.85-0.95) —
  **NOT met on the overall LOO**.

## Why the overall LOO targets are the wrong yardstick here
The 9 catastrophic LOO cases are all tiny hour-1 launches (164-6,400) with
90x-2120x peak ratios, plus 3 simultaneous-PC-unlock launches (Wukong 1.57,
MH Wilds 0.65, RE Requiem 1.20). Those regimes are nearly unpredictable
from hour-1 alone and the final will not be in them. The final is a
console-only, rolling-midnight, giant launch (hour-1 likely 500k-2M).
Relevant subsets (all at spread 1.0):
| subset | n | mean loss | cov90 |
|---|---|---|---|
| console-only + hour-1 >= 100k (final's regime) | 3 | **0.1609** | 0.841 |
| console-only + hour-1 >= 50k | 5 | **0.1568** | 0.859 |
| console-only | 8 | 0.1996 | 0.837 |
| hour-1 >= 100k | 16 | 0.2499 | 0.671 |
| hour-1 >= 250k | 6 | ~0.122 | — |

Spread note: widening the spread to 2.5 improves the overall LOO
(0.4168 -> 0.4016, cov 0.846) but HURTS the final's regime
(console+big 0.1609 -> 0.1861), because big console launches are already
well-predicted and a wide interval only adds pinball penalty. Spread 1.0
is the right choice for the final.

## Why the ensemble, not the regression alone
Regression alone scores better on practice (0.1965) and LOO (0.3915).
But those are interpolations. The final is an EXTRAPOLATION (hour-1
500k-2M, above the largest comparable 875k). Measured at hour-1 = 2M,
hour 19: regression predicts 0.754x (peak below hour-1 — an extrapolation
artifact), pooled+ramp 1.073x, kNN 0.997x, ensemble median 1.0x (guarded).
The ensemble stays sensible where the single regression breaks down.

## Other checks
- Determinism: main.py run twice on p00 — byte-identical output.
- Format: all practice outputs pass the RULES format check (23 rows,
  hours 2-24, 5 non-decreasing quantiles, >0 and <=1e9, <=65,536 bytes).
- Runtime: 0.06-0.07 s/case (limit 8 s).
- 42-comparable pseudo-case (p00's 38 + 4 practice launches as
  comparables 39-42): runs, valid output (1,452 bytes), deterministic.
- Guards ablation: --no-guards LOO 0.4194 vs 0.4190 with guards —
  guards are a safety net, not a performance lever; kept.
- Steepness feature (hour-1 / pre-release max, corr -0.84 with peak
  ratio) tested as a distance term: no measurable gain on practice or
  LOO — reverted, code kept clean.

## Bottom line (honest)
The entry is competitive for the final's regime (console+big LOO 0.161,
practice 0.232 vs house baseline 0.387) but the design's literal
practice (<=0.13) and overall-LOO criteria are NOT met. Whether it beats
the house superbot on the final is not verifiable from practice data —
the house model's score is unknown. Submit-or-not is the coordinator's /
Sky's call.
