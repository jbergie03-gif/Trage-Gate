"""Anytime-TD model v2: logistic regression on scoring-role features.

v1 (`td_model.py`) estimated a player's share of team touchdowns from carries
and targets, and lost to the market because it was too flat -- it could not tell
a red-zone specialist from someone with the same target count between the 20s.

v2 keeps the same skeleton (team touchdowns come from the market's implied
total, per the game-level finding) but learns the player term from features that
describe scoring role rather than volume:

    logit P(1+ TD) = b0 + b1*log(expected_team_tds)
                        + b2*rz_target_share  + b3*gl_carry_share
                        + b4*snap_share       + b5*carry_share
                        + b6*target_share     + b7*td_share

All player features are prior-games-only exponentially weighted means, so no row
sees its own game. Coefficients are fit on seasons before `test_start` only.
"""
import numpy as np
import pandas as pd

import features
import td_model

HALFLIFE = 4.0
USAGE_MIN = 0.03
WINDOW = 17   # trailing games for the stable usage windows, spanning seasons
FEATS = ["log_team_tds", "rz_share", "gl_share", "snap_share",
         "rz_share_w", "gl_share_w", "rz_rate",
         "carry_share_prior", "target_share_prior", "td_share",
         "is_qb", "is_rb", "is_te"]


def assemble():
    """Player-games with prior-only features and the market's implied team total."""
    stats = td_model.load_stats(min_season=2016)
    base = td_model.build(stats)
    games = td_model.load_games().rename(columns={"team": "recent_team"})
    df = base.merge(games, on=["season", "week", "recent_team"], how="left")

    rz = features.build()
    df = df.merge(rz, on=["season", "week", "recent_team", "player_id"], how="left")
    df[["rz_targets", "gl_carries", "team_rz_targets", "team_gl_carries"]] = df[
        ["rz_targets", "gl_carries", "team_rz_targets", "team_gl_carries"]].fillna(0)
    df["rz_target_share"] = df.rz_targets / df.team_rz_targets.replace(0, np.nan)
    df["gl_carry_share"] = df.gl_carries / df.team_gl_carries.replace(0, np.nan)

    snaps = features.snap_shares()
    df["name_key"] = df.player_display_name.map(features.norm_name)
    df = df.merge(snaps, on=["season", "week", "recent_team", "name_key"], how="left")

    df = df.sort_values(["player_id", "season", "week"])
    grp = df.groupby("player_id", sort=False)

    def prior(col):
        return grp[col].transform(
            lambda s: s.shift(1).ewm(halflife=HALFLIFE, min_periods=1).mean())

    df["rz_share"] = prior("rz_target_share").fillna(0)
    df["gl_share"] = prior("gl_carry_share").fillna(0)
    df["snap_share"] = prior("snap_pct").fillna(0)

    # Trailing-window versions. A four-game EWMA of an event that happens ~3
    # times a game is mostly noise, and a season-to-date total is zero in week 1
    # -- exactly when the model gets used -- so these windows deliberately span
    # the season boundary.
    def window_sum(col):
        return grp[col].transform(
            lambda s: s.shift(1).rolling(WINDOW, min_periods=1).sum())

    for col in ("rz_targets", "gl_carries", "team_rz_targets", "team_gl_carries"):
        df[f"w_{col}"] = window_sum(col).fillna(0)
    df["games_prior"] = grp["tds"].transform(
        lambda s: s.shift(1).rolling(WINDOW, min_periods=1).count()).fillna(0)
    df["rz_share_w"] = df.w_rz_targets / df.w_team_rz_targets.replace(0, np.nan)
    df["gl_share_w"] = df.w_gl_carries / df.w_team_gl_carries.replace(0, np.nan)
    df["rz_rate"] = df.w_rz_targets / df.games_prior.replace(0, np.nan)
    df[["rz_share_w", "gl_share_w", "rz_rate"]] = df[
        ["rz_share_w", "gl_share_w", "rz_rate"]].fillna(0)

    # Quarterbacks score on designed runs and sneaks, which no share feature
    # describes; position carries that.
    pos = df.position.fillna("")
    df["is_qb"] = (pos == "QB").astype(int)
    df["is_rb"] = pos.isin(["RB", "FB"]).astype(int)
    df["is_te"] = (pos == "TE").astype(int)

    df["scored"] = (df.tds > 0).astype(int)
    return df


def fit_logit(x, y, ridge=1e-3):
    x = np.c_[np.ones(len(x)), x]
    b = np.zeros(x.shape[1])
    pen = ridge * np.eye(x.shape[1])
    pen[0, 0] = 0
    for _ in range(60):
        p = 1 / (1 + np.exp(-x @ b))
        w = np.clip(p * (1 - p), 1e-6, None)
        grad = x.T @ (y - p) - pen @ b
        hess = x.T @ (x * w[:, None]) + pen
        step = np.linalg.solve(hess, grad)
        b += step
        if np.abs(step).max() < 1e-9:
            break
    return b


def predict(b, frame):
    x = np.c_[np.ones(len(frame)), frame[FEATS].values]
    return 1 / (1 + np.exp(-(x @ b)))


def run(test_start=2020):
    df = assemble()
    train_games = df[df.season < test_start]
    coef_team = td_model.fit_team_tds(train_games)

    df["exp_team_tds"] = (coef_team[0] + coef_team[1] * df.implied_pts).clip(0.5, 6.0)
    df["log_team_tds"] = np.log(df.exp_team_tds)

    usable = df[df.implied_pts.notna() & (df.usage_prior >= USAGE_MIN)].copy()
    train = usable[usable.season < test_start]
    test = usable[usable.season >= test_start].copy()

    b = fit_logit(train[FEATS].values, train.scored.values)
    print(f"fit on {len(train):,} player-games, {int(train.season.min())}-{test_start - 1}")
    for name, value in zip(["intercept"] + FEATS, b):
        print(f"  {name:20s} {value:+.3f}")

    test["p_v2"] = predict(b, test)

    # v1, refit on the same training window for a fair comparison
    lam_train = (train.td_share * train.exp_team_tds).clip(0.001, 3.0)
    lam_test = (test.td_share * test.exp_team_tds).clip(0.001, 3.0)
    test["p_v1"], _ = td_model.platt(lam_train, train.scored, lam_test)

    base = train.scored.mean()
    print(f"\ntest {len(test):,} player-games {test_start}-{int(test.season.max())}"
          f"  actual rate {test.scored.mean():.3f}")
    print(f"  Brier flat base rate : {td_model.brier(np.full(len(test), base), test.scored):.5f}")
    print(f"  Brier v1 (usage)     : {td_model.brier(test.p_v1, test.scored):.5f}")
    print(f"  Brier v2 (scoring)   : {td_model.brier(test.p_v2, test.scored):.5f}")
    print(f"  spread of predictions: v1 sigma {test.p_v1.std():.3f}"
          f"   v2 sigma {test.p_v2.std():.3f}")

    print("\nablation (drop features, refit, rescore):")
    for drop in (["rz_share", "rz_share_w", "rz_rate"],
                 ["gl_share", "gl_share_w"],
                 ["snap_share"],
                 ["is_qb", "is_rb", "is_te"],
                 ["rz_share", "rz_share_w", "rz_rate", "gl_share",
                  "gl_share_w", "snap_share"],
                 ["td_share"]):
        keep = [f for f in FEATS if f not in drop]
        bb = fit_logit(train[keep].values, train.scored.values)
        p = 1 / (1 + np.exp(-(np.c_[np.ones(len(test)), test[keep].values] @ bb)))
        delta = td_model.brier(p, test.scored) - td_model.brier(test.p_v2, test.scored)
        print(f"  without {', '.join(drop):38s} Brier {td_model.brier(p, test.scored):.5f}"
              f"  ({delta:+.5f})")

    # Does red-zone role help where it should -- receivers, and the high-priced
    # end of the board -- even if it washes out over all player-games?
    rz_feats = ["rz_share", "rz_share_w", "rz_rate"]
    keep = [f for f in FEATS if f not in rz_feats]
    bb = fit_logit(train[keep].values, train.scored.values)
    test["p_no_rz"] = 1 / (1 + np.exp(
        -(np.c_[np.ones(len(test)), test[keep].values] @ bb)))
    print("\nred-zone features by subgroup (negative delta = they help):")
    groups = {
        "WR": test.position == "WR",
        "TE": test.position == "TE",
        "RB/FB": test.position.isin(["RB", "FB"]),
        "top-quartile rz_share_w": test.rz_share_w >= test.rz_share_w.quantile(0.75),
        "model p >= 0.30": test.p_v2 >= 0.30,
    }
    for label, mask in groups.items():
        sub = test[mask]
        with_rz = td_model.brier(sub.p_v2, sub.scored)
        without = td_model.brier(sub.p_no_rz, sub.scored)
        print(f"  {label:26s} n={len(sub):6d}  with {with_rz:.5f}"
              f"  without {without:.5f}  delta {with_rz - without:+.5f}")

    print("\nv2 calibration:")
    bins = pd.cut(test.p_v2, [0, .1, .2, .3, .4, .5, .7, 1.0])
    cal = test.groupby(bins, observed=True).agg(
        n=("scored", "size"), predicted=("p_v2", "mean"), actual=("scored", "mean"))
    for idx, r in cal.iterrows():
        print(f"  {str(idx):12s} n={int(r.n):6d}  predicted {r.predicted:.3f}"
              f"  actual {r.actual:.3f}")
    return test, b, coef_team


if __name__ == "__main__":
    run()
