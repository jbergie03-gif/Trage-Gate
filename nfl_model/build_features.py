"""Aggregate nflverse play-by-play into one row per team-game.

Everything downstream (EPA ratings, QB values, totals, travel) reads this file
instead of re-parsing 200 MB of play-by-play. Offensive rows are built from
plays where a team has the ball; the defensive columns are the same numbers
viewed from the other side, joined on game_id.

Output: data/team_games.csv, one row per (game_id, team).
"""
import argparse
import os

import pandas as pd

COLS = [
    "game_id", "season", "week", "season_type", "posteam", "defteam",
    "home_team", "away_team", "play_type", "epa", "success", "qb_dropback",
    "pass_attempt", "rush_attempt", "passer_player_id", "passer_player_name",
    "yards_gained", "roof", "surface", "temp", "wind",
    "drive", "fixed_drive", "half_seconds_remaining", "game_seconds_remaining",
    "cpoe", "xpass", "pass_oe", "qtr", "score_differential", "wp", "play_id",
]

# "Neutral" = the game is still close enough that play-calling reflects
# preference rather than the scoreboard. Garbage time inflates pass rate and
# deflates pace, which is what makes raw team pass-rate ranks misleading.
NEUTRAL_WP = (0.20, 0.80)


def season_frame(path):
    df = pd.read_csv(path, compression="gzip", low_memory=False,
                     usecols=lambda c: c in COLS)
    # Scrimmage plays only: kickoffs, punts and kneels tell us nothing about
    # offensive quality, and kneels actively poison EPA.
    df = df.sort_values(["game_id", "play_id"])
    # Seconds this snap consumed, measured within a drive so the clock stoppage
    # between drives and at the half is not counted as tempo.
    df["sec_per_play"] = (df.groupby(["game_id", "fixed_drive"])
                          ["game_seconds_remaining"].diff(-1))
    df = df[df["play_type"].isin(["pass", "run"])]
    return df


def neutral(df):
    lo, hi = NEUTRAL_WP
    return df[(df["wp"].between(lo, hi)) & (df["qtr"] <= 3)
              & (df["score_differential"].abs() <= 10)]


def aggregate(df):
    g = df.groupby(["game_id", "posteam"], dropna=True)
    out = g.agg(
        season=("season", "first"),
        week=("week", "first"),
        plays=("epa", "size"),
        epa_play=("epa", "mean"),
        success=("success", "mean"),
        dropbacks=("qb_dropback", "sum"),
        pass_plays=("pass_attempt", "sum"),
        rush_plays=("rush_attempt", "sum"),
        drives=("fixed_drive", "nunique"),
        roof=("roof", "first"),
        surface=("surface", "first"),
        temp=("temp", "first"),
        wind=("wind", "first"),
        home_team=("home_team", "first"),
        away_team=("away_team", "first"),
    ).reset_index()

    pas = df[df["pass_attempt"] == 1].groupby(["game_id", "posteam"])["epa"].mean()
    rus = df[df["rush_attempt"] == 1].groupby(["game_id", "posteam"])["epa"].mean()
    out = out.join(pas.rename("epa_pass"), on=["game_id", "posteam"])
    out = out.join(rus.rename("epa_rush"), on=["game_id", "posteam"])

    # Completion percentage over expectation and pass rate over expectation,
    # both nflverse-modelled columns, plus explosive-play rates.
    key = ["game_id", "posteam"]
    cpoe = df.groupby(key)["cpoe"].mean().rename("cpoe")
    proe = df.groupby(key)["pass_oe"].mean().rename("proe")
    xpl_p = df[df["pass_attempt"] == 1].groupby(key).apply(
        lambda s: (s["yards_gained"] >= 20).mean(), include_groups=False
    ).rename("explosive_pass")
    xpl_r = df[df["rush_attempt"] == 1].groupby(key).apply(
        lambda s: (s["yards_gained"] >= 10).mean(), include_groups=False
    ).rename("explosive_rush")
    for s in (cpoe, proe, xpl_p, xpl_r):
        out = out.join(s, on=key)

    nu = neutral(df)
    n_rate = nu.groupby(key)["pass_attempt"].mean().rename("neutral_pass_rate")
    n_epa = nu.groupby(key)["epa"].mean().rename("neutral_epa")
    n_sec = nu.groupby(key)["sec_per_play"].median().rename("neutral_sec_per_play")
    for s in (n_rate, n_epa, n_sec):
        out = out.join(s, on=key)

    # Starting QB = whoever took the most dropbacks. This is ground truth for
    # training; for an upcoming game the depth chart and injury report stand in.
    qb = df[df["qb_dropback"] == 1].groupby(
        ["game_id", "posteam", "passer_player_id", "passer_player_name"]
    ).size().rename("db").reset_index()
    qb = qb.sort_values("db").groupby(["game_id", "posteam"]).tail(1)
    qb = qb.rename(columns={"passer_player_id": "qb_id",
                            "passer_player_name": "qb_name",
                            "db": "qb_dropbacks"})
    out = out.merge(qb, on=["game_id", "posteam"], how="left")

    out["team"] = out["posteam"]
    out["opp"] = out.apply(
        lambda r: r["away_team"] if r["team"] == r["home_team"] else r["home_team"],
        axis=1)
    out["is_home"] = (out["team"] == out["home_team"]).astype(int)
    return out.drop(columns=["posteam"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="/home/ubuntu/nflmodel/data")
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2026)
    a = p.parse_args()

    frames = []
    for year in range(a.start, a.end + 1):
        path = os.path.join(a.data, f"pbp_{year}.csv.gz")
        if not os.path.exists(path):
            print(f"{year}: missing, skipped")
            continue
        df = aggregate(season_frame(path))
        frames.append(df)
        print(f"{year}: {len(df)} team-games")

    all_df = pd.concat(frames, ignore_index=True)
    out = os.path.join(a.data, "team_games.csv")
    all_df.to_csv(out, index=False)
    print(f"wrote {out}: {len(all_df)} rows, {all_df['season'].min()}-"
          f"{all_df['season'].max()}")


if __name__ == "__main__":
    main()
