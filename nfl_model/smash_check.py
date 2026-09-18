"""Is Fantasy Guru's SMASH line rating new information, or our own data back?

The pages keep no archive, so this reads one dated snapshot from
`fantasyguru_pull.py --dataset smash` and asks two questions of it:

1. Does the offensive-line rating look like a stable grade of a line, or like
   the season so far? A grade should track last season too; a results number
   only tracks the games already played.
2. Does the per-game O-line advantage say anything the closing spread does not?

    python3 smash_check.py --snapshot ~/fgdata/smash/2026-09-18 --week 2

Neither question can be settled from one week. This exists so the claim in the
README is reproducible, and so the same check can be re-run once enough weekly
snapshots are stored to test out of sample.
"""
import argparse
import datetime
import os

import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
FG = os.path.expanduser(os.environ.get("FG_OUT", "~/fgdata"))

# Their ratings page spells teams out; the matchups page uses codes, two of
# which are not nflverse's.
NAME = {
    "Arizona": "ARI", "Atlanta": "ATL", "Baltimore": "BAL", "Buffalo": "BUF",
    "Carolina": "CAR", "Chicago": "CHI", "Cincinnati": "CIN",
    "Cleveland": "CLE", "Dallas": "DAL", "Denver": "DEN", "Detroit": "DET",
    "Green Bay": "GB", "Houston": "HOU", "Indianapolis": "IND",
    "Jacksonville": "JAX", "Kansas City": "KC", "Las Vegas": "LV",
    "LA Chargers": "LAC", "Los Angeles Chargers": "LAC",
    "LA Rams": "LA", "Los Angeles Rams": "LA", "Miami": "MIA",
    "Minnesota": "MIN", "New England": "NE", "New Orleans": "NO",
    "NY Giants": "NYG", "New York Giants": "NYG",
    "NY Jets": "NYJ", "New York Jets": "NYJ", "Philadelphia": "PHI",
    "Pittsburgh": "PIT", "San Francisco": "SF", "Seattle": "SEA",
    "Tampa Bay": "TB", "Tennessee": "TEN", "Washington": "WAS",
}
CODE = {"WSH": "WAS", "LAR": "LA"}


def blocking(season):
    """Each offense's pass EPA per dropback and sack rate allowed."""
    want = {"posteam", "sack", "epa", "qb_dropback"}
    p = pd.read_csv(os.path.join(DATA, f"pbp_{season}.csv.gz"),
                    compression="gzip", low_memory=False,
                    usecols=lambda c: c in want)
    d = p[(p["qb_dropback"] == 1) & p["posteam"].notna()]
    g = d.groupby("posteam").agg(sack_rate=("sack", "mean"),
                                 pass_epa=("epa", "mean"),
                                 dropbacks=("epa", "size"))
    return g.reset_index().rename(columns={"posteam": "team"})


def ratings(snapshot, seasons):
    r = pd.read_csv(os.path.join(snapshot, "ratings.csv"))
    r["team"] = r["Team"].map(NAME)
    missing = r[r["team"].isna()]["Team"].tolist()
    if missing:
        print(f"unmapped teams: {missing}")
    r = r.dropna(subset=["team"])
    for season in seasons:
        m = r.merge(blocking(season), on="team")
        print(f"\n{season}: {len(m)} teams, {m.dropbacks.sum():,} dropbacks")
        for col in ("pass_epa", "sack_rate"):
            print(f"  SMASH offensive line vs own {col}: "
                  f"r = {m['Offensive Line'].corr(m[col]):+.3f}")


def matchups(snapshot, season, week):
    m = pd.read_csv(os.path.join(snapshot, "matchups.csv"))
    m["adv"] = m["O-LINE ADV (HOME)"] - m["O-LINE ADV (AWAY)"]
    m["away"] = m["AWAY"].replace(CODE)
    m["home"] = m["HOME"].replace(CODE)
    g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
    g = g[(g.season == season) & (g.week == week)]
    line = dict(zip(zip(g.away_team, g.home_team), g.spread_line))
    m["spread"] = [line.get((a, h)) for a, h in zip(m.away, m.home)]
    have = m.dropna(subset=["spread"])
    print(f"\nmatchups joined to a closing line: {len(have)} of {len(m)}")
    print("  home O-line advantage vs closing spread: "
          f"r = {have['adv'].corr(have['spread']):+.3f}")
    return have[["away", "home", "adv", "spread"]]


def main():
    latest = os.path.join(FG, "smash",
                          datetime.date.today().strftime("%Y-%m-%d"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default=latest,
                    help="a dated ~/fgdata/smash directory")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=2,
                    help="the week the matchups page is showing")
    ap.add_argument("--against", default="2026,2025",
                    help="seasons of our own blocking numbers to compare to")
    args = ap.parse_args()

    seasons = [int(s) for s in args.against.split(",")]
    ratings(args.snapshot, seasons)
    print(matchups(args.snapshot, args.season, args.week)
          .to_string(index=False))


if __name__ == "__main__":
    main()
