"""Totals model: price the over/under with features built for a sum.

`game_model.py` fits the total on the margin model's design matrix, whose
efficiency columns are all *differences* between the two teams. A difference
is the right shape for a margin and the wrong one for a total -- a shootout
and a slog can have the same `net_epa_play`. This file fits the total on the
sums instead (both offenses, both defenses, both quarterbacks, both teams'
scoring pace) plus the league's running scoring level and the weather.

Two numbers come out of it, and they answer different questions:

* `pred_total`   -- the model on its own, never shown the line. This is the
                    one scored against the closing total, because a model
                    that has seen the line cannot be tested against it.
* `blend_total`  -- line + k * (pred_total - line), with k fit walk-forward
                    on prior seasons. This is the best estimate of the score,
                    since the line is the more accurate number and the model
                    only earns the share of the disagreement it has shown it
                    knows. Use this for an implied score; use the first for
                    the record.

Usage:
    python3 total_model.py --report              # walk-forward vs the close
    python3 total_model.py --coefs               # what the total is made of
    python3 total_model.py --predict 2026-09-28  # one slate, both numbers
"""
import argparse

import numpy as np
import pandas as pd

import game_model
from game_model import ridge

FEATURES = [
    *[f"off_sum_{m}" for m in game_model.NET],
    *[f"def_sum_{m}" for m in game_model.NET],
    *[f"sum_{m}" for m in game_model.TEND],
    "qb_sum", "qb_new_sum", "inj_off_sum", "inj_def_sum",
    "pts_pace", "league_total",
    "short_week_home", "short_week_away", "bye_home", "bye_away",
    "primetime", "late_window", "week1", "div_game",
    "dome", "wind", "temp", "cold", "turf", "neutral",
]

BLEND_K0 = 0.25     # share of the disagreement the blend keeps before any
                    # season has been scored; roughly what the old fit earned


def _done(df):
    return df[df["result"].notna() & df["total_line"].notna()].copy()


def blend_k(p):
    """Slope of actual total on (model - line), holding the line fixed.

    Fit on scored predictions only. A slope of 1 would mean the model's
    disagreement is fully real; 0 would mean the line already has it all.
    Clipped to [0, 1] because either extreme past that is noise.
    """
    if len(p) < 200:
        return BLEND_K0
    X = np.column_stack([np.ones(len(p)), p.total_line,
                         p.pred_total - p.total_line])
    beta, *_ = np.linalg.lstsq(X, p.total.values, rcond=None)
    return float(np.clip(beta[2], 0.0, 1.0))


def fit_report(df, first_test=2019):
    """Expanding-window walk-forward: train on prior seasons, test the next.

    The blend's k for a test season is fit on the *predictions* made for the
    seasons before it, so it is walk-forward twice over: the model never sees
    its test season, and the blend never sees how the model did on it.
    """
    done = _done(df)
    preds = []
    for season in range(first_test, int(done["season"].max()) + 1):
        tr = done[done["season"] < season]
        te = done[done["season"] == season]
        if len(tr) < 200 or te.empty:
            continue
        m = ridge().fit(tr[FEATURES].values, tr["total"].values)
        out = te[["game_id", "season", "week", "home_team", "away_team",
                  "spread_line", "total_line", "result", "total"]].copy()
        out["pred_total"] = m.predict(te[FEATURES].values)
        k = blend_k(pd.concat(preds)) if preds else BLEND_K0
        out["blend_k"] = k
        out["blend_total"] = out.total_line + k * (out.pred_total - out.total_line)
        preds.append(out)
    return pd.concat(preds, ignore_index=True)


def _disagree(p, col="pred_total"):
    X = np.column_stack([np.ones(len(p)), p.total_line, p[col] - p.total_line])
    beta, *_ = np.linalg.lstsq(X, p.total.values, rcond=None)
    resid = p.total.values - X @ beta
    s2 = resid @ resid / (len(p) - 3)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return beta, beta / se


def summarize(p):
    print(f"out-of-sample games: {len(p)}  seasons "
          f"{p.season.min()}-{p.season.max()}\n")
    for name, col in (("model", "pred_total"), ("blend", "blend_total"),
                      ("market", "total_line")):
        print(f"total MAE  {name:6s} {(p[col] - p.total).abs().mean():.2f}")

    ou = p[p.total != p.total_line]
    over = ou.pred_total > ou.total_line
    hit = np.where(over, ou.total > ou.total_line, ou.total < ou.total_line)
    print(f"\nO/U taking the model's side  {hit.mean()*100:.1f}%  "
          f"({hit.sum()}/{len(ou)})   blind under "
          f"{(ou.total < ou.total_line).mean()*100:.1f}%")
    edge = (ou.pred_total - ou.total_line).abs().values
    for lo, hi in [(0, 1), (1, 3), (3, 5), (5, 99)]:
        m = (edge >= lo) & (edge < hi)
        if m.sum():
            print(f"  |model - line| {lo}-{hi}: {hit[m].mean()*100:5.1f}%  "
                  f"n={m.sum():4d}")

    beta, t = _disagree(p)
    print("\ntotal ~ line + (model - line)")
    print(f"  line coef      {beta[1]:.3f}  t={t[1]:.2f}")
    print(f"  disagree coef  {beta[2]:.3f}  t={t[2]:.2f}")
    print("  by season, since a pooled t-stat can be one good year:")
    for season, g in p.groupby("season"):
        if len(g) < 50:
            continue
        b, ts = _disagree(g)
        print(f"    {season}  {b[2]:+.3f}  t={ts[2]:+.2f}  n={len(g)}"
              f"   blend k used {g.blend_k.iloc[0]:.2f}")

    print("\nmodel MAE by week bucket:")
    for lo, hi, name in [(1, 1, "week 1"), (2, 4, "weeks 2-4"),
                         (5, 12, "weeks 5-12"), (13, 30, "week 13+")]:
        s = p[(p.week >= lo) & (p.week <= hi)]
        if len(s):
            print(f"  {name:11s} n={len(s):4d}  model "
                  f"{(s.pred_total-s.total).abs().mean():.2f}  blend "
                  f"{(s.blend_total-s.total).abs().mean():.2f}  market "
                  f"{(s.total_line-s.total).abs().mean():.2f}")


def predict_slate(df, season=None, week=None, gameday=None):
    """Fit on every completed game, price one slate. The live entry point."""
    done = _done(df)
    up = df[df["gameday"] == gameday] if gameday else \
        df[(df["season"] == season) & (df["week"] == week)]
    up = up[up["total_line"].notna()].copy()
    if up.empty:
        return up
    m = ridge().fit(done[FEATURES].values, done["total"].values)
    up["pred_total"] = m.predict(up[FEATURES].values)
    k = blend_k(fit_report(df))
    up["blend_k"] = k
    up["blend_total"] = up.total_line + k * (up.pred_total - up.total_line)
    return up.sort_values("gameday")


def note(edge):
    """One phrase for the sheet, on the same scale as the spread note."""
    a = abs(edge)
    if a < 1.5:
        return "total: coin flip"
    side = "over" if edge > 0 else "under"
    if a < 3.5:
        return f"total: lean {side}, edge {a:.1f} inside the error bar"
    return f"total: {side}, edge {a:.1f}"


def coefficients(df, boots=400, seed=0):
    done = _done(df)
    X, y = done[FEATURES].values, done["total"].values
    m = ridge().fit(X, y)
    alpha = m[-1].alpha_
    sd = X.std(axis=0)
    coef = m[-1].coef_ / m[0].scale_
    rng = np.random.default_rng(seed)
    draws = np.empty((boots, len(FEATURES)))
    for b in range(boots):
        i = rng.integers(0, len(X), len(X))
        f = game_model.make_pipeline(game_model.StandardScaler(),
                                     game_model.Ridge(alpha=alpha)).fit(X[i], y[i])
        draws[b] = f[-1].coef_ / f[0].scale_ * sd
    lo, hi = np.percentile(draws, [2.5, 97.5], axis=0)
    z = draws.mean(axis=0) / draws.std(axis=0)
    print(f"\nfull-sample coefficients on total, alpha={alpha:.2f}, "
          f"{boots} bootstrap resamples")
    print(f"{'feature':26s} {'pts/unit':>9s} {'pts/1sd':>8s} "
          f"{'95% CI (pts/1sd)':>20s} {'z':>6s}")
    for i in sorted(range(len(FEATURES)), key=lambda i: -abs(z[i])):
        print(f"  {FEATURES[i]:26s} {coef[i]:+9.3f} {coef[i]*sd[i]:+8.2f} "
              f"  [{lo[i]:+6.2f}, {hi[i]:+6.2f}] {z[i]:+6.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--coefs", action="store_true")
    ap.add_argument("--predict", help="gameday, e.g. 2026-09-28")
    a = ap.parse_args()

    df = game_model.build(*game_model.load())
    if a.report:
        summarize(fit_report(df))
    if a.coefs:
        coefficients(df)
    if a.predict:
        up = predict_slate(df, gameday=a.predict)
        margin = game_model.predict_slate(df, gameday=a.predict)
        margin = dict(zip(margin.game_id, margin.pred_margin))
        print(f"{'game':14s} {'line':>6s} {'model':>6s} {'edge':>6s} "
              f"{'blend':>6s}  {'note':32s} implied score (blend total, "
              f"model margin)")
        for _, r in up.iterrows():
            e = r.pred_total - r.total_line
            mg = margin.get(r.game_id, r.spread_line)
            h = (r.blend_total + mg) / 2
            aw = (r.blend_total - mg) / 2
            print(f"{r.away_team:>3s} @ {r.home_team:<3s}     "
                  f"{r.total_line:6.1f} {r.pred_total:6.1f} {e:+6.1f} "
                  f"{r.blend_total:6.1f}  {note(e):32s} "
                  f"{r.home_team} {h:.1f} - {r.away_team} {aw:.1f}")
        print(f"\nblend k = {up.blend_k.iloc[0]:.2f} (share of the model's "
              f"disagreement kept, fit on scored seasons)")


if __name__ == "__main__":
    main()
