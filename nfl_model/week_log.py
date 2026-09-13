"""Write this week's model numbers next to the market line, timestamped.

This is the record-keeping half of the content plan: predictions get written
down *before* kickoff so the hit rate is auditable later instead of remembered
charitably. It logs model-vs-line, not recommendations -- the backtest says this
model does not beat the closing spread or the closing total.

Both the spread and the total are logged. The total is here because the model's
disagreement with it is the only test in this repo to clear t=2 (+0.269, t=2.14
on 1,943 games) while still converting to a 50.3% O/U record. That combination
is exactly what a forward record settles and a backtest cannot.
"""
import argparse
import datetime
import zoneinfo

import pandas as pd

import game_model
import market_flow

LOG = "/home/ubuntu/ff/2026_Pickem_Log.md"
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def features():
    g, tg, inj = game_model.load()
    return game_model.build(g, tg, inj)


def score(season=2026):
    """Score the model against the line on games that have since been played."""
    df = features()
    p = game_model.fit_report(df, first_test=season)
    p = p[p["season"] == season]
    if p.empty:
        print(f"no completed {season} games with a line yet")
        return
    ats = p[p["result"] != p["spread_line"]]
    ats_hit = ((ats.pred_margin - ats.spread_line)
               * (ats.result - ats.spread_line) > 0)
    ou = p[p["total"] != p["total_line"]]
    ou_hit = ((ou.pred_total - ou.total_line)
              * (ou.total - ou.total_line) > 0)
    print(f"{season}: {len(p)} completed games")
    print(f"  margin MAE  model {(p.pred_margin - p.result).abs().mean():.2f}"
          f"   market {(p.spread_line - p.result).abs().mean():.2f}")
    print(f"  total  MAE  model {(p.pred_total - p.total).abs().mean():.2f}"
          f"   market {(p.total_line - p.total).abs().mean():.2f}")
    print(f"  straight up {((p.pred_margin > 0) == (p.result > 0)).mean():.1%}")
    print(f"  ATS         {ats_hit.sum()}/{len(ats)} = {ats_hit.mean():.1%}"
          "  (break-even at -110 is 52.4%)")
    print(f"  O/U         {ou_hit.sum()}/{len(ou)} = {ou_hit.mean():.1%}")


def main():
    df = features()
    season, week = game_model.next_slate(df)
    if season is None:
        print("no upcoming games with a posted line")
        return
    slate = game_model.predict_slate(df, season, week)
    now = datetime.datetime.now(PACIFIC)
    lines = [
        f"\n## {season} Week {week} — logged {now:%Y-%m-%d %H:%M} PT\n",
        "Model is the walk-forward ridge in `nfl_model/game_model.py`. Out of",
        "sample it measured **worse** than the closing line on both markets",
        "(margin 10.23 vs 9.82, total 10.87 vs 10.38), so these are logged to",
        "score the model, **not** as recommended bets. Margin columns are",
        "expected home margin, so positive means the home team is favored.\n",
        "| Game | Spread | Model | Δ | Total | Model total | Δ | Market note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    # Where the tickets are and where the number went, logged in the same row
    # as the prediction rather than in a second report: the point of interest
    # only matters while the pick is being made, and most games have none.
    notes = market_flow.slate_notes(season, week)
    for r in slate.itertuples():
        tot = (f"{r.total_line:.1f}" if not pd.isna(r.total_line) else "—")
        tot_edge = ("—" if pd.isna(r.total_line)
                    else f"{r.pred_total - r.total_line:+.1f}")
        lines.append(
            f"| {r.away_team} @ {r.home_team} | {r.spread_line:+.1f} "
            f"| {r.pred_margin:+.1f} | {r.pred_margin - r.spread_line:+.1f} "
            f"| {tot} | {r.pred_total:.1f} | {tot_edge} "
            f"| {notes.get((r.away_team, r.home_team)) or ''} |")
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
