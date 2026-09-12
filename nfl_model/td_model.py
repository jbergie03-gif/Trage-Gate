"""Anytime-touchdown probability model, walk-forward, scored by Brier.

Why this market: Kalshi's anytime-TD books are quoted ~1c wide with real open
interest, unlike the wide-but-dead rushing-attempt books. So an accurate
probability is worth something there.

Structure:
    lambda(player, game) = td_share(player) * expected_offensive_tds(team, game)
    P(1+ TD)             = 1 - exp(-lambda)

td_share is the player's share of his team's offensive TDs, estimated from
prior games only and shrunk toward a usage-based prior (carries + targets) so
that a back who has scored twice in two games isn't credited with a 100% share.

expected_offensive_tds comes from the market's implied team total, which is the
one input we should not try to beat -- the game-level backtest showed the line
carries essentially all the information.

Everything is shifted: no row ever uses its own game's stats.
"""
import numpy as np
import pandas as pd

STATS = "/home/ubuntu/nflmodel/data/player_stats.csv"          # legacy file, 1999-2024
STATS_RECENT = "/home/ubuntu/nflmodel/data/spw_{year}.csv"      # stats_player_week_YYYY, 2025+
GAMES = "/home/ubuntu/nflmodel/data/games.csv"
RECENT_YEARS = (2025, 2026)

SHRINK = 8.0          # team-TDs of prior weight pulling share toward usage prior
USAGE_MIN = 0.03      # ignore players with negligible projected involvement
EWM_HALFLIFE = 4.0    # games


def load_games():
    g = pd.read_csv(GAMES, low_memory=False)
    g = g[g.game_type == "REG"]
    rows = []
    for _, r in g.iterrows():
        if pd.isna(r.spread_line) or pd.isna(r.total_line):
            continue
        # spread_line is home-favored-positive
        home_pts = r.total_line / 2 + r.spread_line / 2
        away_pts = r.total_line / 2 - r.spread_line / 2
        rows.append((r.season, r.week, r.home_team, home_pts))
        rows.append((r.season, r.week, r.away_team, away_pts))
    return pd.DataFrame(rows, columns=["season", "week", "team", "implied_pts"])


def load_stats(min_season=2010):
    cols = ["player_id", "player_display_name", "position", "recent_team", "season",
            "week", "season_type", "carries", "targets", "rushing_tds", "receiving_tds"]
    s = pd.read_csv(STATS, usecols=cols, low_memory=False)
    # nflverse split the weekly stats into stats_player_week_YYYY from 2025 on,
    # where recent_team was renamed to team
    recent = []
    for year in RECENT_YEARS:
        r = pd.read_csv(STATS_RECENT.format(year=year), low_memory=False)
        r = r.rename(columns={"team": "recent_team"})
        recent.append(r[[c for c in cols if c in r.columns]])
    s = pd.concat([s] + recent, ignore_index=True)
    s = s[(s.season_type == "REG") & (s.season >= min_season)].copy()
    s["tds"] = s.rushing_tds.fillna(0) + s.receiving_tds.fillna(0)
    s["carries"] = s.carries.fillna(0)
    s["targets"] = s.targets.fillna(0)
    s = s.sort_values(["season", "week"]).reset_index(drop=True)
    return s


def build(stats):
    """Attach prior-only usage and TD-share features to every player-game."""
    team = stats.groupby(["season", "week", "recent_team"], as_index=False).agg(
        team_tds=("tds", "sum"), team_carries=("carries", "sum"),
        team_targets=("targets", "sum"))
    df = stats.merge(team, on=["season", "week", "recent_team"], how="left")

    df["carry_share"] = df.carries / df.team_carries.replace(0, np.nan)
    df["target_share"] = df.targets / df.team_targets.replace(0, np.nan)
    df = df.sort_values(["player_id", "season", "week"])

    grp = df.groupby("player_id", sort=False)
    ewm = lambda col: (grp[col].transform(
        lambda s: s.shift(1).ewm(halflife=EWM_HALFLIFE, min_periods=1).mean()))
    df["carry_share_prior"] = ewm("carry_share").fillna(0)
    df["target_share_prior"] = ewm("target_share").fillna(0)

    # cumulative prior TDs and prior team TDs, within season (resets each year)
    seas = df.groupby(["player_id", "season"], sort=False)
    df["cum_tds"] = seas["tds"].transform(lambda s: s.shift(1).cumsum()).fillna(0)
    df["cum_team_tds"] = seas["team_tds"].transform(lambda s: s.shift(1).cumsum()).fillna(0)

    # usage prior: roughly what fraction of team TDs a player with this usage scores
    df["usage_prior"] = 0.85 * df.carry_share_prior + 0.55 * df.target_share_prior
    df["usage_prior"] = df.usage_prior.clip(0, 0.6)

    df["td_share"] = ((df.cum_tds + SHRINK * df.usage_prior)
                      / (df.cum_team_tds + SHRINK))
    # shares must partition a team's touchdowns, or lambda's scale is arbitrary
    df["td_share"] = (df.td_share
                      / df.groupby(["season", "week", "recent_team"])
                        .td_share.transform("sum"))
    return df


def fit_team_tds(df):
    """Offensive TDs a team scores, as a function of its implied point total."""
    t = df.drop_duplicates(["season", "week", "recent_team"])[
        ["season", "week", "recent_team", "team_tds", "implied_pts"]].dropna()
    A = np.c_[np.ones(len(t)), t.implied_pts.values]
    coef, *_ = np.linalg.lstsq(A, t.team_tds.values, rcond=None)
    return coef


def platt(train_lam, train_y, lam):
    """Logistic recalibration on log-lambda. The raw Poisson probability is
    systematically overconfident at the top of the range; this fixes the map
    from model score to probability without changing the ranking."""
    x = np.c_[np.ones(len(train_lam)), np.log(train_lam)]
    y = np.asarray(train_y, dtype=float)
    b = np.zeros(2)
    for _ in range(50):  # Newton-Raphson
        p = 1 / (1 + np.exp(-x @ b))
        w = np.clip(p * (1 - p), 1e-6, None)
        step = np.linalg.solve(x.T @ (x * w[:, None]) + 1e-6 * np.eye(2), x.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-8:
            break
    z = np.c_[np.ones(len(lam)), np.log(lam)] @ b
    return 1 / (1 + np.exp(-z)), b


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def run(test_start=2018):
    stats = load_stats()
    games = load_games()
    df = build(stats).merge(
        games.rename(columns={"team": "recent_team"}),
        on=["season", "week", "recent_team"], how="left")

    train = df[df.season < test_start]
    coef = fit_team_tds(train)
    print(f"team offensive TDs = {coef[0]:+.3f} + {coef[1]:.4f} * implied_points")

    test = df[(df.season >= test_start) & df.implied_pts.notna()].copy()
    test = test[test.usage_prior >= USAGE_MIN]

    def lam_of(frame):
        return (frame.td_share * (coef[0] + coef[1] * frame.implied_pts)).clip(0.001, 3.0)

    fit = train[train.implied_pts.notna() & (train.usage_prior >= USAGE_MIN)]
    lam_train, y_train = lam_of(fit), (fit.tds > 0).astype(int)

    lam = lam_of(test)
    test["p_raw"] = 1 - np.exp(-lam)
    test["p_model"], b = platt(lam_train, y_train, lam)
    print(f"calibration fit on {len(fit):,} rows: logit(p) = {b[0]:+.3f} {b[1]:+.3f}*log(lambda)")
    test["scored"] = (test.tds > 0).astype(int)

    base_rate = train.assign(s=(train.tds > 0).astype(int)).s.mean()
    # baseline 2: player's own season-to-date rate, shrunk to the base rate
    seas = test.groupby(["player_id", "season"], sort=False)
    prior_games = seas["scored"].transform(lambda s: s.shift(1).expanding().count()).fillna(0)
    prior_hits = seas["scored"].transform(lambda s: s.shift(1).expanding().sum()).fillna(0)
    test["p_player_rate"] = (prior_hits + 4 * base_rate) / (prior_games + 4)

    print(f"\ntest rows {len(test):,}  seasons {test_start}-{int(test.season.max())}"
          f"  actual 1+TD rate {test.scored.mean():.3f}")
    print(f"  Brier, flat base rate      : {brier(np.full(len(test), base_rate), test.scored):.5f}")
    print(f"  Brier, player season rate  : {brier(test.p_player_rate, test.scored):.5f}")
    print(f"  Brier, raw Poisson         : {brier(test.p_raw, test.scored):.5f}")
    print(f"  Brier, calibrated model    : {brier(test.p_model, test.scored):.5f}")

    print("\ncalibration (model):")
    bins = pd.cut(test.p_model, [0, .1, .2, .3, .4, .5, .7, 1.0])
    cal = test.groupby(bins, observed=True).agg(
        n=("scored", "size"), predicted=("p_model", "mean"), actual=("scored", "mean"))
    for idx, r in cal.iterrows():
        print(f"  {str(idx):12s} n={int(r.n):6d}  predicted {r.predicted:.3f}  actual {r.actual:.3f}")
    return test


if __name__ == "__main__":
    run()
