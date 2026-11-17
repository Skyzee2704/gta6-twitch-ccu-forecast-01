"""Fetch the practice answers from SullyGnome (public API, as NOTICE.txt documents).

For each of the 4 practice launches, fetch ONE calendar month (the release
month) of the "Average viewers" dataset and take the 24 hourly points of the
release day (hours 1..24). Hour 1 must match the case file's `known` print
exactly -- that alignment check proves the fetcher read the right series.

Only 4 games, only their release months. No bulk download (NOTICE.txt asks
not to bulk-download the site).

Usage: python3 tools/fetch_answers.py
Writes tools/answers_practice.json:
  {"p00": {"game": ..., "hour1_known": ..., "hours": {"1": v, ..., "24": v}}, ...}
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT_INPUT = (
    Path(__file__).resolve().parents[2]
    / "kit/gta6-twitch-ccu-forecast-01-kit/input"
)

# (case id, SullyGnome id, URL slug, release year, release month, release day)
GAMES = [
    ("p00", 117671, "Marvel's_Wolverine", 2026, 9, 15),
    ("p01", 28264, "Red_Dead_Redemption_2", 2018, 10, 26),
    ("p02", 65645, "God_of_War_Ragnar%C3%B6k", 2022, 11, 9),
    ("p03", 97296, "Marvel%27s_Spider-Man_2", 2023, 10, 20),
]


def fetch_month(sully_id, slug, year, month):
    url = (
        "https://sullygnome.com/api/charts/linecharts/getconfig/GameViewers/30/0/"
        f"{sully_id}/{slug}/%20/%20/{year}/{month}/%20/0/"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main():
    out = {}
    for case_id, sully_id, slug, year, month, day in GAMES:
        data = fetch_month(sully_id, slug, year, month)
        labels = data["data"]["labels"]
        datasets = {d["label"]: d["data"] for d in data["data"]["datasets"]}
        avg = datasets["Average viewers"]
        first = f"{year:04d}-{month:02d}-{day:02d} 00:00"
        i = labels.index(first)
        hours = {}
        for h in range(1, 25):
            v = avg[i + h - 1]
            if v is None:
                raise ValueError(f"{case_id} hour {h}: no SullyGnome point")
            hours[str(h)] = float(v)
        # Alignment check: hour 1 must equal the case file's known print.
        case = json.loads((KIT_INPUT / f"{case_id}.in").read_text(encoding="utf-8"))
        known1 = next(k for k in case["known"] if k["hour"] == 1)["viewers"]
        if hours["1"] != float(known1):
            raise ValueError(
                f"{case_id}: fetched hour 1 {hours['1']} != case known {known1}"
            )
        out[case_id] = {
            "game": case["game"]["name"],
            "hour1_known": known1,
            "hours": hours,
        }
        print(f"{case_id} {case['game']['name']}: hour1 {known1} verified, "
              f"hours 2-24 fetched")
    (HERE / "answers_practice.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print("wrote tools/answers_practice.json")


if __name__ == "__main__":
    main()
