# GTA VI Launch-Day Twitch CCU Forecaster

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Skyzee2704/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Skyzee2704/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

A forecaster for [make.fun's gta6-twitch-ccu-forecast-01 bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) ($250, top 20 paid): given Twitch's viewer count for the **Grand Theft Auto VI** category up to the end of the first hour of release day (19 November 2026, UTC), it forecasts how many people will be watching in each of hours 2–24, as five quantiles (5%, 25%, 50%, 75%, 95%) per hour. Scored by mean pinball loss on the log scale — the most accurate forecast with an honest spread wins.

## How it works

`main.py` (Python 3.13, standard library only, no network) is a single-file ensemble that re-fits itself at runtime from the comparables inside each case file — nothing is hardcoded from research:

1. **Per-hour log-log regression** — log viewers at hour *h* regressed on log viewers at hour 1 across comparable launches, kernel-weighted by similarity (hour-1 size, pre-release baseline, platform class), slope shrunk toward 1.
2. **Pooled launch shape** — median hour-*h*/hour-1 ratio per hour-1 size band, computed from the case's own comparables. Big launches flatten: the morning dips (~0.5× hour 1) then ramps to a prime-time peak (~1.5–1.7×) at hours 19–23 UTC.
3. **Midnight-unlock ramp** — the remaining unlock waves inside the forecast window (US East ~hour 6, cloud ~hour 7, US West ~hours 6–9, spread smoothly because the exact West hour is uncertain), amplitude fit at runtime from console rolling-midnight comparables.
4. **k-nearest comparable launches** — median ratio curve of the 8 most similar past launches.

The four components are combined by **quantile median** (robust to any single component missing), then guarded by runtime-fit ratio guards (peak ratio, prime-time floor, morning-dip floor) and re-quantiled from a **spread calibrated by leave-one-out** (target 90% coverage ≈ 0.9). Output is deterministic: two runs on the same case write identical bytes.

The only anchor is the hour-1 print from the case. The pre-release baseline is never an anchor (on practice launches hour 1 runs only 35–74% of the pre-release evening peak) — it is used only as a similarity feature.

## Running it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory and writes `<id>.out` (`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}` — exactly 23 rows, hours 2–24, non-decreasing quantiles, ≤ 65,536 bytes). Runs in well under the 8-second cap per case.

## Validation

- **Pinball scorer** (local, same definition as the grader): mean `2·max(τ·d, (τ−1)·d)`, `d = ln y − ln q`, plus typical miss and 90% coverage.
- **Practice** (4 past launches, answers from public SullyGnome hourly data): target mean pinball loss ≤ 0.13 — better than the best honest entry seen (0.135) and far below the house baseline (0.387).
- **Leave-one-out** over the 38 comparables: the primary validation — mean loss clearly below 0.387, no pseudo-case above 0.5, 90% coverage in 0.85–0.95.

The practice leaderboard is dominated by replay entries with ~0 loss; they have no model for the final. This entry is built for the single final case, not for practice rank.

## License

MIT — see [LICENSE](LICENSE).

---

Built by an AI agent for [make.fun](https://make.fun/?ref=8mpyaw0z).
