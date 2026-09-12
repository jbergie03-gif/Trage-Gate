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

Run: python3 studies.py [--travel] [--primetime] [--coaches] [--all]
"""
import argparse
import math
import os

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--travel", action="store_true")
    ap.add_argument("--primetime", action="store_true")
    ap.add_argument("--coaches", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    df = pd.read_csv(FEATURES)
    if a.travel or a.all:
        travel(df)
    if a.primetime or a.all:
        primetime(df)
    if a.coaches or a.all:
        coaches(df)


if __name__ == "__main__":
    main()
