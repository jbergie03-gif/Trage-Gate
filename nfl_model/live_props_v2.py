"""Compare model v2 against Kalshi's live anytime-TD books, with availability applied.

Differences from `live_props.py`:
- probabilities come from `td_logit` (scoring-role logistic) instead of the
  usage-share Poisson
- players listed Out or Doubtful on the nflverse injury report are dropped, and
  Questionable is flagged, which is what the first pass was missing when it
  produced "edges" on backup quarterbacks

Still a research output. The injury report is not the inactive list; it is
published before it, so a healthy-but-benched backup still needs a human look.
"""
import re
import urllib.request
import json

import numpy as np
import pandas as pd

import features
import td_logit
import td_model
from live_props import kalshi_anytime_td, norm, upcoming_implied

DATA = "/home/ubuntu/nflmodel/data"
OUT_STATUS = ("Out", "Doubtful")
SEASON = 2026


def injury_report(season=SEASON):
    inj = pd.read_csv(f"{DATA}/inj_{season}.csv.gz", low_memory=False)
    inj = inj[inj.season_type == "REG"]
    week = int(inj.week.max())
    inj = inj[inj.week == week]
    return week, inj[["gsis_id", "full_name", "team", "report_status",
                      "report_primary_injury", "practice_status"]].rename(
        columns={"gsis_id": "player_id"})


def latest_features():
    """Each player's most recent prior-only feature row, plus fitted coefficients."""
    df = td_logit.assemble()
    coef_team = td_model.fit_team_tds(df[df.season < SEASON])
    df["log_team_tds"] = np.log(
        (coef_team[0] + coef_team[1] * df.implied_pts).clip(0.5, 6.0))
    train = df[(df.season < SEASON) & df.implied_pts.notna()
               & (df.usage_prior >= td_logit.USAGE_MIN)]
    b = td_logit.fit_logit(train[td_logit.FEATS].values, train.scored.values)

    latest = df.sort_values(["season", "week"]).groupby("player_id").tail(1)
    latest = latest[(latest.season >= SEASON - 1)
                    & (latest.usage_prior >= td_logit.USAGE_MIN)].copy()
    latest["td_share"] = (latest.td_share
                          / latest.groupby("recent_team").td_share.transform("sum"))
    latest["key"] = latest.player_display_name.map(norm)
    return latest, coef_team, b


def main(min_gap=0.05):
    book = kalshi_anytime_td()
    if book.empty:
        print("no quoted anytime-TD markets right now")
        return
    latest, coef_team, b = latest_features()
    week, implied = upcoming_implied()
    inj_week, inj = injury_report()

    book["key"] = book.player.map(norm)
    cols = (["key", "player_id", "player_display_name", "position", "recent_team",
             "usage_prior"]
            + [f for f in td_logit.FEATS if f != "log_team_tds"])
    m = book.merge(latest[cols], on="key", how="inner").merge(
        implied, on="recent_team", how="inner")
    m = m.merge(inj[["player_id", "report_status", "report_primary_injury"]],
                on="player_id", how="left")

    m["exp_team_tds"] = (coef_team[0] + coef_team[1] * m.implied_pts).clip(0.5, 6.0)
    m["log_team_tds"] = np.log(m.exp_team_tds)
    m["p_model"] = td_logit.predict(b, m)
    m["edge"] = m.p_model - m.mid

    out = m[m.report_status.isin(OUT_STATUS)]
    live = m[~m.report_status.isin(OUT_STATUS)].copy()

    print(f"market week {week}, injury report week {inj_week}")
    print(f"quoted markets {len(book)}  matched to model {len(m)}"
          f"  dropped Out/Doubtful {len(out)}  remaining {len(live)}")
    print(f"model mean {live.p_model.mean():.3f} sigma {live.p_model.std():.3f}"
          f"   market mean {live.mid.mean():.3f} sigma {live.mid.std():.3f}"
          f"   corr {live.p_model.corr(live.mid):.3f}")

    bucket = pd.cut(live.mid, [0, .1, .2, .3, .5, 1.0])
    print("\nmodel vs market by market price:")
    print(live.groupby(bucket, observed=True).agg(
        n=("edge", "size"), market=("mid", "mean"),
        model=("p_model", "mean"), edge=("edge", "mean")).round(3).to_string())

    if len(out):
        print("\ndropped as Out/Doubtful (market price shown, model would have quoted):")
        print(out[["player", "recent_team", "report_status", "report_primary_injury",
                   "mid", "p_model"]].to_string(index=False,
                                                float_format=lambda v: f"{v:.3f}"))

    show = ["player", "recent_team", "position", "report_status", "implied_pts",
            "snap_share", "yes_bid", "yes_ask", "mid", "p_model", "edge", "oi"]
    big = live[live.edge.abs() >= min_gap].sort_values("edge", ascending=False)
    print(f"\ndisagreements >= {min_gap:.0%}:")
    with pd.option_context("display.width", 220, "display.max_rows", 80):
        print(big[show].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("\nUNVERIFIED as a bet list: the injury report is not the inactive list,"
          " and no depth-chart check is applied.")


if __name__ == "__main__":
    main()
