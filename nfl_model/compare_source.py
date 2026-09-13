"""Compare a subscription stat table against the nflverse-derived numbers.

Given a season, print this model's value and league rank for each metric the
paid table also carries, so the two can be checked against each other.  Metrics
that need charting or tracking data (pressure rate, coverage scheme, YBCO) are
not derivable from play-by-play and are reported as unavailable.

Usage: python3 compare_source.py --season 2025 --teams NO DET
"""
import argparse

import pandas as pd

DATA = "/home/ubuntu/nflmodel/data/team_games.csv"

# metric -> (column, higher_is_better, label)
OFFENSE = [
    ("proe", True, "Pass Rate Over Expectation (PROE)"),
    ("plays", True, "Plays per Game"),
    ("neutral_sec_per_play", False, "Neutral Pace (sec/snap)"),
    ("neutral_pass_rate", True, "Neutral Pass Rate"),
    ("epa_pass", True, "Dropback EPA"),
    ("cpoe", True, "Cmp Pct Over Expectation (CPOE)"),
    ("explosive_pass", True, "Explosive Pass Rate"),
    ("epa_rush", True, "Rushing EPA"),
    ("explosive_rush", True, "Explosive Rush Rate"),
]

# the same metrics measured against a team, i.e. what its defense allowed
DEFENSE = [
    ("epa_pass", False, "D Dropback EPA"),
    ("cpoe", False, "D CPOE"),
    ("explosive_pass", False, "D Explosive Pass Rate"),
    ("epa_rush", False, "D Rushing EPA"),
    ("explosive_rush", False, "D Explosive Rush Rate"),
]

UNAVAILABLE = [
    "Pressure Rate Allowed", "D Pressure Rate",
    "D Zone Coverage Pct", "D Single-High Coverage Pct",
    "D Two-High Coverage Pct", "YBCO/Att", "D YBCO/Att Allowed",
]


def season_table(season):
    """Per-team offensive means, and the means their defenses allowed.

    Regular season only. team_games.csv carries the playoffs too, and leaving
    them in silently rewards the teams that played more games.
    """
    df = pd.read_csv(DATA)
    last_reg = 17 if season <= 2020 else 18
    df = df[(df["season"] == season) & (df["week"] <= last_reg)]
    off = df.groupby("team").mean(numeric_only=True)
    deff = df.groupby("opp").mean(numeric_only=True)
    return off, deff


def ranks(frame, col, higher_is_better):
    return frame[col].rank(ascending=not higher_is_better, method="min")


def report(season, teams):
    off, deff = season_table(season)
    print(f"nflverse-derived, {season} regular season, {len(off)} teams\n")
    header = f"{'metric':<34}" + "".join(f"{t:>18}" for t in teams)
    print(header)
    print("-" * len(header))
    for frame, metrics in ((off, OFFENSE), (deff, DEFENSE)):
        for col, high, label in metrics:
            rank = ranks(frame, col, high)
            cells = ""
            for t in teams:
                if t not in frame.index:
                    cells += f"{'n/a':>18}"
                    continue
                cells += f"{frame.at[t, col]:>12.3f} ({int(rank[t]):>2})"
            print(f"{label:<34}{cells}")
    print("\nnot derivable from play-by-play (needs charting/tracking data):")
    for name in UNAVAILABLE:
        print(f"  {name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=2025)
    p.add_argument("--teams", nargs="+", required=True)
    a = p.parse_args()
    report(a.season, a.teams)


if __name__ == "__main__":
    main()
