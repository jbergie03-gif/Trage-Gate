#!/usr/bin/env python3
"""How much does a team lose when a starting lineman is out?

This is the question the per-player ratings failed at, asked the way it
survives: not "is Lane Johnson better than his backup", which the free data
cannot see, but "does a team that is missing established starters block worse
and lose by more". It needs no opinion about which lineman is good.

A starter is defined walk-forward: a lineman who took at least STARTER of the
snaps in at least START_RATE of his team's previous LOOKBACK games. On game
day that status is already known, so nothing here peeks at the result.

Three tests, in increasing difficulty:

1. blocking -- does the offence's sack rate and pass EPA get worse, after
   subtracting the opponent's effect and the offence's own season baseline?
2. margin -- does the difference in missing starters move the final score?
3. against the market -- does it move the score *beyond* what the closing
   spread already says? The line is set by people who read the injury report,
   so a real effect here means the market underprices it, which is a much
   stronger claim and the only one worth betting.

Test 3 is the one that decides whether this becomes a model feature, and it
is also where this kind of study usually cheats. `--source snaps` calls a man
missing when he took under half the snaps, which a blowout or a mid-game
injury also produces -- so a team being beaten badly *causes* the absence, and
the edge is read backwards out of the result. Two honest alternatives:

* `--source inactive` -- he has no snap row at all, so he did not dress. Still
  decided before kickoff, and immune to being pulled while losing.
* `--source injury` -- he was listed Out or Doubtful on the week's injury
  report. This is the only version the model could actually use on Friday,
  and the only one that is unarguably known in advance.

If the market-beating slope survives `--source injury`, it is worth something.
If it only exists under `--source snaps`, it is the blowout effect wearing a
costume.
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
OL = ("T", "G", "C")
STARTER = 0.5     # snap share that counts as having started a game
START_RATE = 0.6  # share of recent games started to count as a starter
LOOKBACK = 6


def snaps():
    cols = ["season", "week", "game_id", "team", "player", "pfr_player_id",
            "position", "offense_pct"]
    fs = sorted(glob.glob(os.path.join(DATA, "snap_*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=cols) for f in fs],
                  ignore_index=True)
    d = d[d.position.isin(OL) & d.pfr_player_id.notna()]
    return d.sort_values(["season", "week"])


def injured():
    """Names ruled Out or Doubtful on each week's report, by team and week."""
    out = set()
    fs = (glob.glob(os.path.join(DATA, "inj_*.csv"))
          + glob.glob(os.path.join(DATA, "inj_*.csv.gz")))
    for f in sorted(fs):
        d = pd.read_csv(f, usecols=["season", "team", "week", "full_name",
                                    "report_status"])
        d = d[d.report_status.isin(["Out", "Doubtful"])]
        out |= set(zip(d.season, d.team, d.week, d.full_name))
    return out


def missing(d, source="snaps"):
    """Per team-game: how much starting offensive line is absent.

    `ol_out` counts a missing starter as his own usual snap share, so a man who
    plays every down costs a full unit and a rotational starter costs less.
    """
    hurt = injured() if source == "injury" else set()
    rows = []
    for (season, team), g in d.groupby(["season", "team"], sort=False):
        weeks = sorted(g.week.unique())
        # Who was on the roster this season at all; a lineman absent from the
        # snap file for a game did not play it.
        played = {(p, w) for p, w in zip(g.pfr_player_id, g.week)}
        share, name = {}, {}
        for p, pg in g.groupby("pfr_player_id"):
            share[p] = dict(zip(pg.week, pg.offense_pct))
            name[p] = pg.player.iloc[0]
        for i, w in enumerate(weeks):
            prev = weeks[max(0, i - LOOKBACK):i]
            if len(prev) < 3:
                continue
            out, cnt = 0.0, 0
            for p, sh in share.items():
                hist = [sh.get(x, 0.0) for x in prev]
                starts = sum(1 for v in hist if v >= STARTER)
                if starts / len(prev) < START_RATE:
                    continue
                usual = float(np.mean([v for v in hist if v >= STARTER]))
                if source == "injury":
                    gone = (season, team, w, name[p]) in hurt
                elif source == "inactive":
                    gone = (p, w) not in played
                else:
                    gone = (p, w) not in played or sh.get(w, 0.0) < STARTER
                if gone:
                    out += usual
                    cnt += 1
            rows.append({"season": season, "team": team, "week": w,
                         "ol_out": out, "ol_out_n": cnt})
    return pd.DataFrame(rows)


def blocking():
    """Team-game sack rate and pass EPA, opponent- and offence-adjusted."""
    rows = []
    for f in sorted(glob.glob(os.path.join(DATA, "pbp_*.csv.gz"))):
        p = pd.read_csv(f, low_memory=True, usecols=[
            "game_id", "season", "week", "posteam", "defteam", "play_type",
            "sack", "epa"])
        p = p[p.posteam.notna() & p.play_type.isin(["pass", "run"])]
        for (gid, off), g in p.groupby(["game_id", "posteam"], sort=False):
            dp = g[g.play_type == "pass"]
            ru = g[g.play_type == "run"]
            if len(dp) < 10 or len(ru) < 5:
                continue
            rows.append({"season": g.season.iloc[0], "week": g.week.iloc[0],
                         "team": off, "def": g.defteam.iloc[0],
                         "sack_rate": dp.sack.mean(),
                         "pass_epa": dp.epa.mean(),
                         "rush_epa": ru.epa.mean()})
    d = pd.DataFrame(rows)
    for y in ("sack_rate", "pass_epa", "rush_epa"):
        d[y] = (d[y] - d.groupby("def")[y].transform("mean")
                - d.groupby(["season", "team"])[y].transform("mean")
                + 2 * d[y].mean())
    return d


def ols(x, y):
    """Slope, standard error and t for y on x with an intercept."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    a = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(a, y, rcond=None)
    r = y - a @ b
    s2 = r @ r / (len(x) - a.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(a.T @ a)))
    return b[1], se[1], b[1] / se[1], len(x)


def games():
    g = pd.read_csv(os.path.join(DATA, "games.csv"))
    g = g[g.result.notna() & g.spread_line.notna()]
    return g[["season", "week", "home_team", "away_team", "result",
              "spread_line"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="snaps",
                    choices=["snaps", "inactive", "injury"],
                    help="what counts as a starter being missing")
    ap.add_argument("--out", default="/tmp/ol_missing.csv")
    a = ap.parse_args()

    m = missing(snaps(), a.source)
    print(f"missing measured by --source {a.source}\n")
    m.to_csv(a.out, index=False)
    print(f"{len(m):,} team-games, missing starters "
          f"{m.ol_out_n.mean():.2f} on average, "
          f"none in {(m.ol_out_n == 0).mean():.0%} of games, "
          f"three or more in {(m.ol_out_n >= 3).mean():.1%}\n")

    b = blocking().merge(m, on=["season", "team", "week"], how="inner")
    print("1. blocking, per missing starter (weighted by his usual snaps):\n")
    for y in ("sack_rate", "pass_epa", "rush_epa"):
        sl, se, t, n = ols(b.ol_out, b[y])
        print(f"{y:10s} {sl:+.5f} +/- {se:.5f}  t={t:+.2f}  n={n:,}")
    print("\n   by count of starters out:")
    print(b.groupby(b.ol_out_n.clip(upper=3))[
        ["sack_rate", "pass_epa", "rush_epa"]].agg(["mean", "size"]).to_string(
        float_format="%.4f"))

    g = games().merge(
        m.rename(columns={"team": "home_team", "ol_out": "home_out",
                          "ol_out_n": "home_n"}),
        on=["season", "week", "home_team"], how="inner").merge(
        m.rename(columns={"team": "away_team", "ol_out": "away_out",
                          "ol_out_n": "away_n"}),
        on=["season", "week", "away_team"], how="inner")
    # Positive means the away team is the more banged-up line, which should
    # help the home team's margin.
    g["edge"] = g.away_out - g.home_out
    print(f"\n2. margin, {len(g):,} games. Slope is points of home margin per "
          "one missing full-time starter on the away line:\n")
    sl, se, t, n = ols(g.edge, g.result)
    print(f"   margin      {sl:+.3f} +/- {se:.3f}  t={t:+.2f}")

    # The market's own number is spread_line (positive = home favoured).
    g["resid"] = g.result - g.spread_line
    sl, se, t, n = ols(g.edge, g.resid)
    print(f"\n3. against the closing line, same slope on what the market "
          f"missed:\n\n   beat market {sl:+.3f} +/- {se:.3f}  t={t:+.2f}")
    verdict = ("the market underprices missing linemen"
               if abs(t) > 2 else
               "the market already knows -- no bet here")
    print(f"\n   -> {verdict}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
