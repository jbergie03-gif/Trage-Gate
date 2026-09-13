"""Descriptive studies on top of the game feature table.

These answer questions asked directly -- do coast-to-coast trips and early
body-clock kickoffs hurt, do primetime games play differently, which coaches
are good in week 1 and after a bye -- in the one form that is not confounded
by team quality: against the closing spread. A team's straight-up record in
primetime mostly measures that good teams get scheduled in primetime; its
record against the spread does not, because the market has already priced
the team.

Every cell prints its sample size, and a standard error so a 56% on 40 games
is visibly not the same claim as a 56% on 400.

Run: python3 studies.py [--travel] [--primetime] [--coaches] [--totals]
                        [--baseline] [--leak] [--all]
"""
import argparse
import math
import os

import numpy as np
import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
FEATURES = os.path.join(DATA, "game_features.csv")
GAMES = os.path.join(DATA, "games.csv")


def se(p, n):
    return math.sqrt(p * (1 - p) / n) if n else float("nan")


def ats_row(name, s, side="away"):
    """Cover rate for one side of the spread, with sample size and error.

    spread_line is positive when the home team is favored, so the away team's
    margin against the line is result + spread_line... in home-margin terms,
    the away side covers when result < spread_line.
    """
    s = s[s["result"].notna() & s["spread_line"].notna()]
    live = s[s["result"] != s["spread_line"]]          # drop pushes
    if not len(live):
        print(f"  {name:34s} no games")
        return
    cover = ((live["result"] < live["spread_line"]) if side == "away"
             else (live["result"] > live["spread_line"]))
    p, n = cover.mean(), len(live)
    pts = (live["result"] - live["spread_line"]).mean()
    if side == "away":
        pts = -pts
    print(f"  {name:34s} n={n:4d}  {side} cover {p*100:5.1f}%  "
          f"+/-{se(p, n)*100:4.1f}  margin vs line {pts:+5.2f}")


def travel(df):
    print("\n=== TRAVEL AND BODY CLOCK (away side vs the spread) ===")
    print("dist_away is in thousands of miles; bodyclock_away is the kickoff")
    print("hour on the away team's home clock.\n")

    d = df[df["neutral"] == 0]
    print("by distance traveled:")
    for lo, hi in [(0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 9)]:
        s = d[(d.dist_away >= lo) & (d.dist_away < hi)]
        ats_row(f"{lo*1000:.0f}-{hi*1000:.0f} mi", s)

    print("\nby timezone shift (positive = traveling east):")
    for lo, hi, name in [(-9, -1.5, "2+ zones west"), (-1.5, -0.5, "1 west"),
                         (-0.5, 0.5, "same zone"), (0.5, 1.5, "1 east"),
                         (1.5, 9, "2+ zones east")]:
        ats_row(name, d[(d.tz_shift_away >= lo) & (d.tz_shift_away < hi)])

    print("\nthe specific case: west-coast team east for a body-clock morning")
    ats_row("coast_cross_away = 1", d[d.coast_cross_away == 1])
    ats_row("coast_cross_away = 0", d[d.coast_cross_away == 0])

    print("\nby away-team body-clock kickoff hour:")
    for lo, hi, name in [(0, 11, "before 11am body clock"),
                         (11, 14, "11am-2pm"), (14, 17, "2-5pm"),
                         (17, 24, "after 5pm")]:
        ats_row(name, d[(d.bodyclock_away >= lo) & (d.bodyclock_away < hi)])

    print("\nscoring and pace in the same cuts (points, not spread):")
    for name, s in [("all games", d),
                    ("coast_cross_away", d[d.coast_cross_away == 1]),
                    ("2+ zones east", d[d.tz_shift_away >= 1.5]),
                    ("1500+ mi traveled", d[d.dist_away >= 1.5])]:
        t = s[s["total"].notna()]
        print(f"  {name:34s} n={len(t):4d}  total {t['total'].mean():5.2f}  "
              f"home margin {t['result'].mean():+5.2f}")


def primetime(df):
    print("\n=== PRIMETIME AND KICKOFF WINDOW ===")
    print("primetime = kickoff at 7pm venue-local or later (SNF/MNF/TNF and")
    print("the international/holiday windows that share the national slot).\n")

    for name, s in [("primetime", df[df.primetime == 1]),
                    ("late window (not primetime)",
                     df[(df.late_window == 1) & (df.primetime == 0)]),
                    ("early window", df[(df.late_window == 0)
                                        & (df.primetime == 0)])]:
        ats_row(name + " -- home", s, side="home")
        ats_row(name + " -- away", s, side="away")
        t = s[s["total"].notna()]
        print(f"    scoring: n={len(t):4d}  total {t['total'].mean():5.2f}  "
              f"home margin {t['result'].mean():+5.2f}  "
              f"|margin| {t['result'].abs().mean():5.2f}")

    print("\nfavorites vs dogs in primetime:")
    p = df[(df.primetime == 1) & df["result"].notna()]
    fav_home = p[p.spread_line > 0]
    fav_away = p[p.spread_line < 0]
    ats_row("home favorite", fav_home, side="home")
    ats_row("road favorite", fav_away, side="away")


def coaches(df, min_games=8):
    """Week-1 and post-bye records by coach, straight up and against the spread.

    Straight up is the number people quote and the one that mostly measures
    roster quality. ATS is the one that controls for it, because the spread
    already contains the market's read on the team.
    """
    g = pd.read_csv(GAMES)
    g = g[(g["season"] >= 2002) & (g["game_type"] == "REG")]
    g = g[g["result"].notna() & g["spread_line"].notna()]

    long = pd.concat([
        pd.DataFrame({"coach": g["home_coach"], "season": g["season"],
                      "week": g["week"], "team": g["home_team"],
                      "margin": g["result"], "line": g["spread_line"]}),
        pd.DataFrame({"coach": g["away_coach"], "season": g["season"],
                      "week": g["week"], "team": g["away_team"],
                      "margin": -g["result"], "line": -g["spread_line"]}),
    ]).dropna(subset=["coach"])

    long["won"] = long["margin"] > 0
    long["covered"] = long["margin"] > long["line"]
    long["push"] = long["margin"] == long["line"]

    # A bye is a gap in a team's week sequence within a season.
    long = long.sort_values(["season", "team", "week"])
    prev = long.groupby(["season", "team"])["week"].shift(1)
    long["post_bye"] = (long["week"] - prev) > 1

    for label, sub in [("WEEK 1", long[long["week"] == 1]),
                       ("POST-BYE", long[long["post_bye"]])]:
        agg = sub.groupby("coach").apply(lambda s: pd.Series({
            "n": len(s),
            "su": s["won"].mean(),
            "ats_n": (~s["push"]).sum(),
            "ats": s.loc[~s["push"], "covered"].mean(),
        }), include_groups=False)
        agg = agg[agg["n"] >= min_games].sort_values("ats", ascending=False)
        print(f"\n=== {label}: coaches with {min_games}+ games, 2002-2025 ===")
        print(f"  {'coach':22s} {'n':>3s} {'SU':>6s} {'ATS':>6s} {'+/-':>5s}")
        for c, r in agg.iterrows():
            print(f"  {c:22s} {int(r['n']):3d} {r['su']*100:5.1f}% "
                  f"{r['ats']*100:5.1f}% {se(r['ats'], r['ats_n'])*100:4.1f}")
        p = sub.loc[~sub["push"], "covered"].mean()
        n = int((~sub["push"]).sum())
        print(f"  {'-- all coaches':22s} {n:3d} "
              f"{sub['won'].mean()*100:5.1f}% {p*100:5.1f}% {se(p, n)*100:4.1f}")


def ou_row(name, s):
    """Under rate for a slice, with the average line and average result.

    The two averages are the part that says whether a cover rate is a real
    scoring effect or a coin that landed: an under rate of 55% with the line
    and the result on top of each other is noise, and the same 55% with the
    line two points high is the market pricing something that is not there.
    """
    s = s[s["total"].notna() & s["total_line"].notna()]
    live = s[s["total"] != s["total_line"]]            # drop pushes
    if not len(live):
        print(f"  {name:26s} no games")
        return
    p, n = (live["total"] < live["total_line"]).mean(), len(live)
    print(f"  {name:26s} n={n:4d}  under {p*100:5.1f}%  +/-{se(p, n)*100:4.1f}"
          f"   line {live['total_line'].mean():4.1f}  "
          f"actual {live['total'].mean():4.1f}")


def totals(min_season=1999):
    """Week-1 unders: the one totals trend worth a look, and why it is not one.

    Asked because week-1 unders hit 56% in the recent decade. They also hit
    54% in the two decades before it, which is a better argument than the
    single number -- except that the rolling ten-season window drops to 45.6%
    in the middle, so the pooled rate is not a rate the bettor ever faced.
    """
    g = pd.read_csv(GAMES)
    g = g[(g["game_type"] == "REG") & (g["season"] >= min_season)
          & (g["season"] <= 2025)]

    print(f"\n=== TOTALS: week 1 vs the rest, {min_season}-2025 ===")
    print("break-even at -110 is 52.4%\n")
    ou_row("week 1", g[g["week"] == 1])
    ou_row("weeks 2+", g[g["week"] > 1])

    print("\nweek 1 by era:")
    for lo, hi in [(1999, 2005), (2006, 2015), (2016, 2025)]:
        ou_row(f"{lo}-{hi}",
               g[(g["week"] == 1) & g["season"].between(lo, hi)])

    print("\nweek 1 by total posted:")
    for lo, hi in [(0, 42), (42, 47), (47, 99)]:
        s = g[(g["week"] == 1) & g["total_line"].between(lo, hi, "left")]
        ou_row(f"line {lo}-{hi}", s)

    print("\nweek 1, rolling ten seasons -- the reason this is not a trend:")
    for start in range(min_season, 2017):
        s = g[(g["week"] == 1) & g["season"].between(start, start + 9)]
        live = s[s["total"] != s["total_line"]]
        p = (live["total"] < live["total_line"]).mean()
        print(f"  {start}-{start+9}  under {p*100:5.1f}%  n={len(live)}")


def baseline():
    """What the model must beat before the market is even worth discussing.

    Scoring the model only against the closing line flatters it: the line is a
    hard bar, so losing to it looks respectable. The bar that decides whether
    the features earn their keep is a constant -- every game predicted at the
    league's average home margin, every total at the league average. Both
    constants use prior games only, so they are themselves out of sample.
    """
    import game_model

    df = game_model.build(*game_model.load())
    p = (game_model.fit_report(df)
         .dropna(subset=["result", "total", "spread_line", "total_line"])
         .sort_values(["season", "week"]).reset_index(drop=True))

    def mae(pred, actual):
        return float(np.abs(pred - actual).mean())

    prior_margin = p["result"].expanding().mean().shift(1).fillna(0)
    prior_total = (p["total"].expanding().mean().shift(1)
                   .fillna(p["total"].mean()))

    print(f"out-of-sample games: {len(p)}\n")
    print("margin, mean absolute error")
    for name, pred in [("pick'em (always 0)", 0.0),
                       ("always home by 2.5", 2.5),
                       ("prior-games home margin", prior_margin),
                       ("model", p["pred_margin"]),
                       ("closing spread", p["spread_line"])]:
        print(f"  {name:26s} {mae(pred, p['result']):6.2f}")

    print("\ntotal, mean absolute error")
    for name, pred in [("prior-games league mean", prior_total),
                       ("model", p["pred_total"]),
                       ("closing total", p["total_line"])]:
        print(f"  {name:26s} {mae(pred, p['total']):6.2f}")

    print("\nstraight up")
    for name, pick in [("always the home team", p["result"] > 0),
                       ("model", (p["pred_margin"] > 0) == (p["result"] > 0)),
                       ("closing spread",
                        (p["spread_line"] > 0) == (p["result"] > 0))]:
        print(f"  {name:26s} {pick.mean() * 100:5.1f}%")

    # Share of the distance from constant to market that the features close.
    # Reported because the raw error gaps read as small either way.
    for label, dumb, mdl, mkt in [
            ("margin", mae(prior_margin, p["result"]),
             mae(p["pred_margin"], p["result"]),
             mae(p["spread_line"], p["result"])),
            ("total", mae(prior_total, p["total"]),
             mae(p["pred_total"], p["total"]),
             mae(p["total_line"], p["total"]))]:
        print(f"\n{label}: constant {dumb:.2f} -> model {mdl:.2f} -> "
              f"market {mkt:.2f}; features close "
              f"{(dumb - mdl) / (dumb - mkt) * 100:.0f}% of the gap")

    # Mean error punishes a blowout miss that an over/under bettor does not
    # care about, so score the totals model the way the bet actually settles:
    # right side of the posted number or not. The constant guesser is scored
    # the same way, as the floor.
    ou = p[p["total"] != p["total_line"]]
    hit = (((ou["pred_total"] - ou["total_line"])
            * (ou["total"] - ou["total_line"])) > 0)
    robot = (((prior_total.loc[ou.index] - ou["total_line"])
              * (ou["total"] - ou["total_line"])) > 0)
    under = ou["total"] < ou["total_line"]
    print("\ntotal, over/under hit rate (break-even 52.4% at -110)")
    for name, s in [("model's side", hit), ("constant guesser", robot),
                    ("always under", under)]:
        print(f"  {name:26s} {s.mean()*100:5.1f}%  +/-"
              f"{se(s.mean(), len(s))*100:4.1f}  n={len(s)}")
    print("  by size of disagreement with the posted total:")
    for lo, hi in [(0, 1), (1, 3), (3, 5), (5, 99)]:
        m = (ou["pred_total"] - ou["total_line"]).abs().between(lo, hi, "left")
        print(f"    {lo}-{hi} pts{'':16s}{hit[m].mean()*100:5.1f}%  +/-"
              f"{se(hit[m].mean(), int(m.sum()))*100:4.1f}  n={int(m.sum())}")


def leak_ablation():
    """Refit without the features that are not fully knowable pre-kickoff.

    games.csv carries observed game-time weather rather than the forecast, and
    its starting-QB column is the quarterback who actually took the first snap.
    Both are hindsight in a backtest. If dropping them barely moves the error
    the backtest is not being carried by hindsight; if it moves a lot, every
    number quoted from it is inflated.
    """
    import game_model

    df = game_model.build(*game_model.load())
    full = list(game_model.FEATURES)
    cuts = [("full model", full),
            ("no observed weather", [f for f in full
                                     if f not in ("wind", "cold")]),
            ("no QB features", [f for f in full
                                if not f.startswith("qb_")]),
            ("neither", [f for f in full if f not in ("wind", "cold")
                         and not f.startswith("qb_")])]
    try:
        for name, feats in cuts:
            game_model.FEATURES = feats
            p = game_model.fit_report(df)
            su = ((p.pred_margin > 0) == (p.result > 0)).mean() * 100
            print(f"  {name:22s} margin MAE "
                  f"{np.abs(p.pred_margin - p.result).mean():.3f}   "
                  f"total MAE {np.abs(p.pred_total - p.total).mean():.3f}   "
                  f"SU {su:.1f}%")
    finally:
        game_model.FEATURES = full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--travel", action="store_true")
    ap.add_argument("--primetime", action="store_true")
    ap.add_argument("--coaches", action="store_true")
    ap.add_argument("--totals", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--leak", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.baseline or a.all:
        baseline()
    if a.leak or a.all:
        leak_ablation()
    df = pd.read_csv(FEATURES)
    if a.travel or a.all:
        travel(df)
    if a.primetime or a.all:
        primetime(df)
    if a.coaches or a.all:
        coaches(df)
    if a.totals or a.all:
        totals()


if __name__ == "__main__":
    main()
