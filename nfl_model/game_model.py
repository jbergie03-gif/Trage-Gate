"""Game model: build the feature table walk-forward, fit ridge, score it.

Design choices worth knowing before reading the numbers:

* Every feature for a game is computed from games that had already finished,
  so nothing here can see its own result. Ratings update only after the row
  is written.
* The starting quarterback comes from the schedule's announced starter
  (`away_qb_id`/`home_qb_id`), not from who actually threw the passes. That is
  the information available before kickoff, and it is what an upcoming game
  will have.
* Ridge, not feature selection. Small effects are shrunk toward zero rather
  than dropped, so three genuine half-point factors still add up while noise
  gets squeezed. Features are standardized first, otherwise the penalty
  falls almost entirely on EPA (which lives on a 0.1 scale and needs a large
  coefficient) and barely touches the 0/1 dummies.
* Two targets: margin (home - away) and total points.

Usage:
    python3 game_model.py --report
    python3 game_model.py --predict 2026-09-13
"""
import argparse
import datetime as dt
import math
import os
import zoneinfo

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import stadiums
from ratings import Ratings

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
GAMES = os.path.join(DATA, "games.csv")
TEAM_GAMES = os.path.join(DATA, "team_games.csv")
ET = zoneinfo.ZoneInfo("America/New_York")
ALPHAS = np.logspace(-2, 3, 24)


def ridge():
    """Standardize, then ridge with alpha chosen by cross-validation."""
    return make_pipeline(StandardScaler(), RidgeCV(alphas=ALPHAS))


# Matchup differences: (home offense vs away defense) minus the mirror. One
# column per efficiency metric, so the model can weigh passing separately
# from rushing rather than through a single blended number.
NET = ["epa_play", "epa_pass", "epa_rush", "success", "cpoe",
       "explosive_pass", "explosive_rush"]
TEND = ["plays", "proe", "neutral_pass_rate", "neutral_sec_per_play"]

FEATURES = [
    *[f"net_{m}" for m in NET],
    *[f"sum_{m}" for m in TEND],
    *[f"diff_{m}" for m in TEND],
    "qb_diff", "qb_new_home", "qb_new_away",
    "rest_diff", "short_week_home", "short_week_away",
    "bye_home", "bye_away",
    "dist_away", "dist_home", "tz_shift_away", "tz_shift_home",
    "bodyclock_away", "bodyclock_home", "coast_cross_away",
    "primetime", "late_window", "week1", "div_game",
    "dome", "wind", "cold", "turf", "neutral",
]


def haversine(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))  # miles


def kickoff_utc(row):
    """Kickoff as an aware datetime. games.csv gametime is Eastern."""
    t = str(row["gametime"])
    if ":" not in t:
        t = "13:00"
    hh, mm = (int(x) for x in t.split(":")[:2])
    d = dt.date.fromisoformat(str(row["gameday"]))
    return dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


def travel(row):
    """Distance, timezone shift and body-clock kickoff hour for both teams."""
    site = stadiums.site(row["home_team"], row.get("stadium"))
    home = stadiums.STADIUM.get(row["home_team"])
    away = stadiums.STADIUM.get(row["away_team"])
    if site is None or home is None or away is None:
        return dict(dist_away=0.0, dist_home=0.0, tz_shift_away=0.0,
                    tz_shift_home=0.0, bodyclock_away=13.0,
                    bodyclock_home=13.0, coast_cross_away=0.0, neutral=0)

    kick = kickoff_utc(row)
    site_tz = zoneinfo.ZoneInfo(site[2])
    local_hour = kick.astimezone(site_tz).hour + kick.astimezone(site_tz).minute / 60

    def body(team_tz):
        z = zoneinfo.ZoneInfo(team_tz)
        return kick.astimezone(z).hour + kick.astimezone(z).minute / 60

    def utcoff(team_tz):
        return kick.astimezone(zoneinfo.ZoneInfo(team_tz)).utcoffset().total_seconds() / 3600

    neutral = 1 if (site is not home) and site != home else 0
    d_away = haversine((away[0], away[1]), (site[0], site[1]))
    d_home = haversine((home[0], home[1]), (site[0], site[1]))

    # Positive = the team's body clock is behind the venue clock, i.e. an
    # eastward trip, which is the direction that makes an early kickoff hard.
    tz_away = utcoff(site[2]) - utcoff(away[2])
    tz_home = utcoff(site[2]) - utcoff(home[2])

    # The specific case Jonathan asked about: a western team crossing two or
    # more zones east for a body-clock-morning kickoff.
    cross = 1.0 if (tz_away >= 2 and body(away[2]) <= 11.0) else 0.0

    return dict(dist_away=d_away / 1000.0, dist_home=d_home / 1000.0,
                tz_shift_away=tz_away, tz_shift_home=tz_home,
                bodyclock_away=body(away[2]), bodyclock_home=body(home[2]),
                coast_cross_away=cross, neutral=neutral,
                local_hour=local_hour)


def load():
    g = pd.read_csv(GAMES)
    g = g[g["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
    g = g[g["season"] >= 2016].copy()
    tg = pd.read_csv(TEAM_GAMES)
    return g, tg


def build(g, tg):
    tg_by_game = {k: v.to_dict("records") for k, v in tg.groupby("game_id")}
    r = Ratings()
    rows = []
    g = g.sort_values(["season", "week", "gameday", "gametime"])

    for _, row in g.iterrows():
        r.new_season(row["season"])
        home, away = row["home_team"], row["away_team"]
        net = {f"net_{m}": (r.o(m, home) - r.d(m, away))
               - (r.o(m, away) - r.d(m, home)) for m in NET}
        tend = {}
        for m in TEND:
            tend[f"sum_{m}"] = r.t(m, home) + r.t(m, away)
            tend[f"diff_{m}"] = r.t(m, home) - r.t(m, away)
        qh = r.qb_rating(row.get("home_qb_id"))
        qa = r.qb_rating(row.get("away_qb_id"))

        tv = travel(row)
        wind = row["wind"]
        temp = row["temp"]
        dome = 1 if str(row.get("roof")) in ("dome", "closed") else 0
        if dome or pd.isna(wind):
            wind = 0.0
        if pd.isna(temp):
            temp = 70.0 if dome else 60.0

        kick = kickoff_utc(row)
        weekday = str(row.get("weekday"))
        primetime = 1 if (weekday in ("Monday", "Thursday")
                          or (weekday == "Sunday" and kick.hour >= 19)) else 0

        feat = dict(
            game_id=row["game_id"], season=row["season"], week=row["week"],
            gameday=row["gameday"], home_team=home, away_team=away,
            spread_line=row["spread_line"], total_line=row["total_line"],
            result=row["result"], total=row["total"],
            **net, **tend,
            qb_diff=qh - qa,
            qb_new_home=1 if r.qb_seen(row.get("home_qb_id")) < 200 else 0,
            qb_new_away=1 if r.qb_seen(row.get("away_qb_id")) < 200 else 0,
            rest_diff=(row["home_rest"] or 7) - (row["away_rest"] or 7),
            short_week_home=1 if row["home_rest"] <= 4 else 0,
            short_week_away=1 if row["away_rest"] <= 4 else 0,
            bye_home=1 if row["home_rest"] >= 13 else 0,
            bye_away=1 if row["away_rest"] >= 13 else 0,
            primetime=primetime,
            late_window=1 if 16 <= tv.get("local_hour", 13) < 19 else 0,
            week1=1 if row["week"] == 1 else 0,
            div_game=int(row.get("div_game") or 0),
            dome=dome, wind=float(wind),
            cold=1 if temp <= 35 else 0,
            turf=0 if "grass" in str(row.get("surface")) else 1,
            **{k: v for k, v in tv.items() if k != "local_hour"},
        )
        rows.append(feat)

        played = tg_by_game.get(row["game_id"])
        if played and pd.notna(row["result"]):
            r.update_game(played)

    return pd.DataFrame(rows)


def fit_report(df, first_test=2019):
    """Expanding-window walk-forward: train on prior seasons, test on the next."""
    done = df[df["result"].notna() & df["spread_line"].notna()
              & df["total_line"].notna()].copy()
    preds = []
    for season in range(first_test, int(done["season"].max()) + 1):
        tr = done[done["season"] < season]
        te = done[done["season"] == season]
        if len(tr) < 200 or te.empty:
            continue
        Xtr, Xte = tr[FEATURES].values, te[FEATURES].values
        mm = ridge().fit(Xtr, tr["result"].values)
        tm = ridge().fit(Xtr, tr["total"].values)
        out = te[["game_id", "season", "week", "home_team", "away_team",
                  "spread_line", "total_line", "result", "total"]].copy()
        out["pred_margin"] = mm.predict(Xte)
        out["pred_total"] = tm.predict(Xte)
        preds.append(out)
    return pd.concat(preds, ignore_index=True)


def summarize(p):
    print(f"out-of-sample games: {len(p)}  seasons "
          f"{p.season.min()}-{p.season.max()}\n")
    mm = (p.pred_margin - p.result).abs().mean()
    km = (p.spread_line - p.result).abs().mean()
    mt = (p.pred_total - p.total).abs().mean()
    kt = (p.total_line - p.total).abs().mean()
    print(f"margin MAE   model {mm:.2f}   market {km:.2f}")
    print(f"total  MAE   model {mt:.2f}   market {kt:.2f}")

    su_m = ((p.pred_margin > 0) == (p.result > 0)).mean()
    su_k = ((p.spread_line > 0) == (p.result > 0)).mean()
    print(f"straight up  model {su_m*100:.1f}%  market {su_k*100:.1f}%")

    # ATS: take the side the model likes relative to the line.
    live = p[p.result != p.spread_line]
    side = np.where(live.pred_margin > live.spread_line, 1, -1)
    won = np.where(side == 1, live.result > live.spread_line,
                   live.result < live.spread_line)
    print(f"ATS          {won.mean()*100:.1f}%  ({won.sum()}/{len(live)})")

    # The test that matters: does model disagreement explain anything the
    # line does not already explain?
    X = np.column_stack([np.ones(len(p)), p.spread_line,
                         p.pred_margin - p.spread_line])
    beta, *_ = np.linalg.lstsq(X, p.result.values, rcond=None)
    resid = p.result.values - X @ beta
    s2 = resid @ resid / (len(p) - 3)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    print("\nmargin ~ line + (model - line)")
    print(f"  line coef      {beta[1]:.3f}  t={beta[1]/se[1]:.2f}")
    print(f"  disagree coef  {beta[2]:.3f}  t={beta[2]/se[2]:.2f}")
    print("  (t above ~2 on the second row would be a real edge)")

    print("\nby week bucket (margin MAE):")
    for lo, hi, name in [(1, 1, "week 1"), (2, 4, "weeks 2-4"),
                         (5, 12, "weeks 5-12"), (13, 30, "week 13+")]:
        s = p[(p.week >= lo) & (p.week <= hi)]
        if len(s):
            print(f"  {name:11s} n={len(s):4d}  model "
                  f"{(s.pred_margin-s.result).abs().mean():.2f}  market "
                  f"{(s.spread_line-s.result).abs().mean():.2f}")


def coefficients(df, target="result", boots=400, seed=0):
    """Ridge coefficients with bootstrap intervals.

    A textbook OLS standard error is wrong twice over here: the fit is
    penalized, and the travel columns are nearly collinear (distance,
    timezone shift and body-clock hour all encode the same trip), which makes
    the classical covariance matrix singular and prints NaN. Resampling games
    gives an interval that survives both, and it prices the collinearity
    honestly -- two features carrying one effect share the credit and both
    come out wide.
    """
    done = df[df["result"].notna() & df["total_line"].notna()]
    X, y = done[FEATURES].values, done[target].values
    m = ridge().fit(X, y)
    alpha = m[-1].alpha_
    sd = X.std(axis=0)
    coef = m[-1].coef_ / m[0].scale_        # points per natural unit

    rng = np.random.default_rng(seed)
    draws = np.empty((boots, len(FEATURES)))
    for b in range(boots):
        i = rng.integers(0, len(X), len(X))
        f = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(X[i], y[i])
        draws[b] = f[-1].coef_ / f[0].scale_ * sd    # points per 1 sd

    lo, hi = np.percentile(draws, [2.5, 97.5], axis=0)
    z = draws.mean(axis=0) / draws.std(axis=0)
    print(f"\nfull-sample coefficients on {target}, alpha={alpha:.2f}, "
          f"{boots} bootstrap resamples")
    print(f"{'feature':26s} {'pts/unit':>9s} {'pts/1sd':>8s} "
          f"{'95% CI (pts/1sd)':>20s} {'z':>6s}")
    order = sorted(range(len(FEATURES)), key=lambda i: -abs(z[i]))
    for i in order:
        print(f"  {FEATURES[i]:26s} {coef[i]:+9.3f} {coef[i]*sd[i]:+8.2f} "
              f"  [{lo[i]:+6.2f}, {hi[i]:+6.2f}] {z[i]:+6.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--coefs", action="store_true")
    ap.add_argument("--predict", help="gameday, e.g. 2026-09-13")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    g, tg = load()
    df = build(g, tg)
    if a.save:
        out = os.path.join(DATA, "game_features.csv")
        df.to_csv(out, index=False)
        print(f"wrote {out}: {len(df)} games")

    if a.report:
        summarize(fit_report(df))
    if a.coefs:
        coefficients(df, "result")
        coefficients(df, "total")

    if a.predict:
        done = df[df["result"].notna() & df["total_line"].notna()]
        up = df[df["gameday"] == a.predict]
        mm = ridge().fit(done[FEATURES].values, done["result"].values)
        tm = ridge().fit(done[FEATURES].values, done["total"].values)
        up = up.copy()
        up["pred_margin"] = mm.predict(up[FEATURES].values)
        up["pred_total"] = tm.predict(up[FEATURES].values)
        print(f"{'game':14s} {'model':>7s} {'line':>7s} {'edge':>6s} "
              f"{'m_tot':>6s} {'tot':>6s}  score")
        for _, r in up.iterrows():
            h = (r.pred_total + r.pred_margin) / 2
            aw = (r.pred_total - r.pred_margin) / 2
            edge = r.pred_margin - r.spread_line
            print(f"{r.away_team:>3s} @ {r.home_team:<3s}     "
                  f"{r.pred_margin:+7.1f} {r.spread_line:+7.1f} {edge:+6.1f} "
                  f"{r.pred_total:6.1f} {r.total_line:6.1f}  "
                  f"{r.home_team} {h:.1f} - {r.away_team} {aw:.1f}")


if __name__ == "__main__":
    main()
