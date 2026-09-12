"""Elo margin model for NFL games, scored against the closing line.

The only question this answers: does a cheap model beat the market's number?
Everything is walk-forward -- ratings at prediction time never see the result.

Data: nflverse games.csv (1999-present), which carries closing spread_line,
total_line and moneylines alongside results.
"""
import argparse
import csv
import math
from collections import defaultdict

DATA = "/home/ubuntu/nflmodel/data/games.csv"

# spread_line in nflverse is from the home team's perspective, positive = home favored.
HFA_PRIOR = 2.0
K = 20.0
REVERT = 0.25  # pull toward 1500 between seasons
SCALE = 25.0   # elo points per point of margin


def load(path=DATA):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r["game_type"] not in ("REG", "WC", "DIV", "CON", "SB"):
                continue
            try:
                season = int(r["season"])
                week = int(r["week"])
            except ValueError:
                continue
            hs, as_ = r["home_score"], r["away_score"]
            rows.append({
                "game_id": r["game_id"],
                "season": season,
                "week": week,
                "gameday": r["gameday"],
                "home": r["home_team"],
                "away": r["away_team"],
                "home_score": int(hs) if hs else None,
                "away_score": int(as_) if as_ else None,
                "spread_line": float(r["spread_line"]) if r["spread_line"] else None,
                "total_line": float(r["total_line"]) if r["total_line"] else None,
                "home_rest": int(r["home_rest"]) if r["home_rest"] else None,
                "away_rest": int(r["away_rest"]) if r["away_rest"] else None,
                "neutral": r["location"] != "Home",
            })
    rows.sort(key=lambda g: (g["season"], g["week"], g["gameday"]))
    return rows


class Elo:
    def __init__(self, k=K, hfa=HFA_PRIOR, revert=REVERT, scale=SCALE):
        self.k, self.hfa, self.revert, self.scale = k, hfa, revert, scale
        self.r = defaultdict(lambda: 1500.0)
        self.season = None

    def _roll_season(self, season):
        if self.season is not None and season != self.season:
            for t in self.r:
                self.r[t] = 1500.0 + (self.r[t] - 1500.0) * (1 - self.revert)
        self.season = season

    def predict(self, g):
        """Projected home margin, in points."""
        self._roll_season(g["season"])
        edge = (self.r[g["home"]] - self.r[g["away"]]) / self.scale
        if not g["neutral"]:
            edge += self.hfa
        return edge

    def update(self, g, pred):
        actual = g["home_score"] - g["away_score"]
        err = actual - pred
        # margin-of-victory multiplier, damped so blowouts don't dominate
        mult = math.log(abs(actual) + 1) * 1.5
        delta = self.k * (err / self.scale) * mult / 4.0
        self.r[g["home"]] += delta
        self.r[g["away"]] -= delta


def backtest(rows, start_season, k=K, hfa=HFA_PRIOR, revert=REVERT, scale=SCALE,
             edge_threshold=0.0, verbose=True):
    model = Elo(k, hfa, revert, scale)
    n = ats_w = ats_l = ats_p = 0
    se_model = se_market = 0.0
    bets = []
    for g in rows:
        if g["home_score"] is None:
            continue
        pred = model.predict(g)
        if g["season"] >= start_season and g["spread_line"] is not None:
            actual = g["home_score"] - g["away_score"]
            market = g["spread_line"]
            n += 1
            se_model += (actual - pred) ** 2
            se_market += (actual - market) ** 2
            edge = pred - market
            if abs(edge) >= edge_threshold:
                # bet the side the model likes
                cover = actual - market
                if abs(cover) < 1e-9:
                    ats_p += 1
                elif (edge > 0) == (cover > 0):
                    ats_w += 1
                else:
                    ats_l += 1
                bets.append((g, pred, market, actual))
        model.update(g, pred)

    graded = ats_w + ats_l
    out = {
        "games": n,
        "rmse_model": math.sqrt(se_model / n) if n else float("nan"),
        "rmse_market": math.sqrt(se_market / n) if n else float("nan"),
        "bets": graded,
        "pushes": ats_p,
        "ats_pct": ats_w / graded if graded else float("nan"),
        "wins": ats_w,
        "losses": ats_l,
        "model": model,
    }
    if verbose:
        print(f"seasons {start_season}+   graded games: {n}")
        print(f"  RMSE model  : {out['rmse_model']:.3f} pts")
        print(f"  RMSE market : {out['rmse_market']:.3f} pts   <- the number to beat")
        if graded:
            # -110 juice needs 52.38%
            roi = (ats_w * (100 / 110) - ats_l) / graded * 100
            print(f"  ATS at edge>={edge_threshold}: {ats_w}-{ats_l}-{ats_p} "
                  f"= {100*out['ats_pct']:.2f}%  (break-even 52.38%)  ROI {roi:+.2f}%")
        print()
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2015)
    p.add_argument("--edge", type=float, default=0.0)
    a = p.parse_args()
    rows = load()
    print(f"loaded {len(rows)} games, {rows[0]['season']}-{rows[-1]['season']}\n")
    backtest(rows, a.start, edge_threshold=a.edge)
