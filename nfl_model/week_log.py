"""Write this week's model numbers next to the market line, timestamped.

This is the record-keeping half of the content plan: predictions get written
down *before* kickoff so the hit rate is auditable later instead of remembered
charitably. It logs model-vs-line, not recommendations -- the backtest says this
model does not beat the closing spread.
"""
import argparse
import datetime
import math
import zoneinfo

import pandas as pd

import elo
import market_flow

LOG = "/home/ubuntu/ff/2026_Pickem_Log.md"
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def upcoming_and_ratings():
    rows = elo.load()
    model = elo.Elo()
    played, upcoming = [], []
    for g in rows:
        if g["home_score"] is None or pd.isna(g["home_score"]):
            upcoming.append(g)
        else:
            played.append(g)
    for g in played:
        model.update(g, model.predict(g))
    season = max(g["season"] for g in upcoming)
    week = min(g["week"] for g in upcoming if g["season"] == season)
    slate = [g for g in upcoming if g["season"] == season and g["week"] == week]
    return model, season, week, slate


def score(season=2026):
    """Score the model against the line on games that have since been played."""
    rows = elo.load()
    model = elo.Elo()
    n = mse_model = mse_market = ats = 0
    for g in rows:
        pred = model.predict(g)
        if g["home_score"] is None:
            continue
        actual = g["home_score"] - g["away_score"]
        if g["season"] == season and g["spread_line"] is not None:
            n += 1
            mse_model += (actual - pred) ** 2
            mse_market += (actual - g["spread_line"]) ** 2
            # did the side the model preferred beat the line?
            if (pred - g["spread_line"]) * (actual - g["spread_line"]) > 0:
                ats += 1
        model.update(g, pred)
    if not n:
        print(f"no completed {season} games with a line yet")
        return
    print(f"{season}: {n} completed games")
    print(f"  model RMSE  {math.sqrt(mse_model / n):.3f}")
    print(f"  market RMSE {math.sqrt(mse_market / n):.3f}")
    print(f"  model ATS   {ats}/{n} = {ats / n:.1%}  (break-even at -110 is 52.4%)")


def main():
    model, season, week, slate = upcoming_and_ratings()
    now = datetime.datetime.now(PACIFIC)
    lines = [
        f"\n## {season} Week {week} — logged {now:%Y-%m-%d %H:%M} PT\n",
        "Model is the walk-forward Elo in `nfl_model/elo.py`. It measured **worse**",
        "than the closing spread out of sample (13.24 vs 12.72 RMSE), so these are",
        "logged to score the model, **not** as recommended bets. Both columns are",
        "expected home margin in points, so positive means the home team is favored.\n",
        "| Game | Market (home margin) | Model (home margin) | Model − market | Market note |",
        "|---|---|---|---|---|",
    ]
    # Where the tickets are and where the number went, logged in the same row
    # as the prediction rather than in a second report: the point of interest
    # only matters while the pick is being made, and most games have none.
    notes = market_flow.slate_notes(season, week)
    for g in sorted(slate, key=lambda g: g["gameday"]):
        pred = model.predict(g)
        market = g["spread_line"]
        if market is None or pd.isna(market):
            continue
        lines.append(f"| {g['away']} @ {g['home']} | {market:+.1f} | {pred:+.1f} "
                     f"| {pred - market:+.1f} "
                     f"| {notes.get((g['away'], g['home'])) or ''} |")
    lines.append("")
    lines.append("Player-level entries are deliberately absent: projections are not logged "
                 "until inactives and depth charts are verified for every player named.")
    lines.append("")
    with open(LOG, "a") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true",
                    help="score completed games instead of logging the next slate")
    args = ap.parse_args()
    score() if args.score else main()
