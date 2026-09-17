#!/usr/bin/env python3
"""Does the offensive line move a game, and can a free feed see it?

Three questions, in order, because the later ones only matter if the earlier
ones answer yes:

1. Can the feed see the unit at all? PFR snap counts name each lineman and the
   position he played that game, but only as T/G/C -- a left tackle moving to
   right tackle is invisible, a guard moving to tackle is not.
2. Does a unit's continuity show up in what the line is paid to do (sacks and
   pressures allowed, rush EPA), after the opponent and the quarterback are
   accounted for?
3. Does any of it survive in the margin, where the model actually competes?

A rating that fails 2 or 3 is noise that sounds expert, so it is measured here
before it is allowed anywhere near game_model.py.
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
OL = ("T", "G", "C")
STARTER = 0.5          # share of offensive snaps that counts as "he played"
LOOKBACK = 17          # games of history that define a lineman's usual spot


def snaps():
    """Every offensive lineman's snap share per game, all seasons on disk."""
    cols = ["season", "week", "game_id", "team", "opponent", "player",
            "pfr_player_id", "position", "offense_snaps", "offense_pct"]
    fs = sorted(glob.glob(os.path.join(DATA, "snap_*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=cols) for f in fs],
                  ignore_index=True)
    d = d[d.position.isin(OL) & d.pfr_player_id.notna()]
    return d.sort_values(["season", "week"]).reset_index(drop=True)


def usual_spot(d):
    """The position each lineman played most in his previous LOOKBACK games.

    Walk-forward on purpose: the usual spot is what was known before kickoff,
    so a player who moves in week 5 and never moves back still counts as out
    of position in week 5.
    """
    d = d.sort_values(["pfr_player_id", "season", "week"]).copy()
    out = []
    for _, g in d.groupby("pfr_player_id", sort=False):
        pos = g.position.tolist()
        prior = []
        for i in range(len(pos)):
            hist = pos[max(0, i - LOOKBACK):i]
            prior.append(max(set(hist), key=hist.count) if hist else None)
        out.append(pd.Series(prior, index=g.index))
    d["usual"] = pd.concat(out)
    return d


def unit(d):
    """One row per team-game: who started, how settled the five were.

    `carry` is the snap-weighted share of this unit that also started the
    team's previous game -- the continuity number. `oop` counts starters lined
    up somewhere other than their usual spot.
    """
    d = usual_spot(d)
    st = d[d.offense_pct >= STARTER].copy()
    rows = []
    prev = {}
    for (season, week, team), g in st.groupby(["season", "week", "team"],
                                              sort=True):
        ids = set(g.pfr_player_id)
        last = prev.get((season, team), set())
        held = len(ids & last) / max(len(ids), 1) if last else np.nan
        oop = int(((g.usual.notna()) & (g.usual != g.position)).sum())
        rows.append({"season": season, "week": week, "team": team,
                     "game_id": g.game_id.iloc[0], "starters": len(ids),
                     "carry": held, "oop": oop,
                     "oop_snaps": float(g.loc[(g.usual.notna())
                                              & (g.usual != g.position),
                                              "offense_pct"].sum())})
        prev[(season, team)] = ids
    return pd.DataFrame(rows)


def outcomes():
    """What the line is paid to do, per team-game, from play-by-play."""
    rows = []
    for f in sorted(glob.glob(os.path.join(DATA, "pbp_*.csv.gz"))):
        p = pd.read_csv(f, low_memory=True, compression="gzip", usecols=[
            "game_id", "season", "week", "posteam", "defteam", "play_type",
            "sack", "qb_hit", "epa", "rush_attempt", "pass_attempt"])
        p = p[p.posteam.notna() & p.play_type.isin(["pass", "run"])]
        for (gid, off), g in p.groupby(["game_id", "posteam"], sort=False):
            dp = g[g.play_type == "pass"]
            ru = g[g.play_type == "run"]
            if len(dp) < 10 or len(ru) < 5:
                continue
            rows.append({
                "game_id": gid, "team": off, "def": g.defteam.iloc[0],
                "season": g.season.iloc[0], "week": g.week.iloc[0],
                "dropbacks": len(dp), "sack_rate": dp.sack.mean(),
                "hit_rate": dp.qb_hit.mean(),
                "pass_epa": dp.epa.mean(), "rush_epa": ru.epa.mean()})
    return pd.DataFrame(rows)


def residualize(df, y, by):
    """y minus the mean of y for each group in `by`, done one group at a time.

    Crude but readable: it takes the opponent and the offense's own baseline
    out of the outcome so what is left is closer to "this line, this week".
    """
    r = df[y].astype(float).copy()
    for col in by:
        r = r - df.groupby(col)[y].transform("mean") + df[y].mean()
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/ol_study.csv")
    a = ap.parse_args()

    s = snaps()
    print(f"{len(s):,} lineman-game rows, "
          f"{s.season.min()}-{s.season.max()}, "
          f"{s.pfr_player_id.nunique():,} linemen")

    u = unit(s)
    o = outcomes()
    m = u.merge(o, on=["game_id", "team", "season", "week"], how="inner")
    print(f"{len(m):,} team-games matched to play-by-play")
    print(f"out-of-position starters: {(m.oop > 0).mean():.1%} of team-games, "
          f"{m.oop.sum():,} players")
    print(f"continuity: median {m.carry.median():.2f}, "
          f"{(m.carry <= 0.6).mean():.1%} of games below 0.6")

    for y in ("sack_rate", "hit_rate", "pass_epa", "rush_epa"):
        m[f"r_{y}"] = residualize(m, y, ["def", "team"])
    m.to_csv(a.out, index=False)

    print("\ncontinuity vs what the line is paid to do (adjusted for "
          "opponent and offense):")
    fit = m[m.carry.notna()]
    for y in ("sack_rate", "hit_rate", "pass_epa", "rush_epa"):
        lo = fit[fit.carry <= 0.6][f"r_{y}"].mean()
        hi = fit[fit.carry >= 1.0][f"r_{y}"].mean()
        c = fit[["carry", f"r_{y}"]].corr().iloc[0, 1]
        print(f"  {y:10s} settled {hi:+.4f}  shuffled {lo:+.4f}  "
              f"gap {hi - lo:+.4f}  r={c:+.3f}")

    print("\nout of position vs the same:")
    for y in ("sack_rate", "hit_rate", "pass_epa", "rush_epa"):
        a0 = m[m.oop == 0][f"r_{y}"].mean()
        a1 = m[m.oop >= 1][f"r_{y}"].mean()
        print(f"  {y:10s} in spot {a0:+.4f}  moved {a1:+.4f}  "
              f"gap {a1 - a0:+.4f}  n={int((m.oop >= 1).sum())}")

    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
