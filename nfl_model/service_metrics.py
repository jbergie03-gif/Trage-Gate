"""What a prediction *service* can honestly advertise.

Beating the closing line (see `elo.py`) and being accurate are different bars.
A subscriber asks "how often are you right?", not "do you have positive EV
against a market maker". This scores the second question:

- straight-up winner accuracy, model vs the market's favorite vs picking home
- win-probability calibration and Brier skill
- margin and total error in points
- how often the model even disagrees with the line

Walk-forward: every prediction is made before the game is graded.
"""
import math

import elo

SIGMA = 13.3   # points; the sd of actual margin around a point spread


def win_prob(margin):
    """Normal CDF of a margin -- P(home wins) given a projected margin."""
    return 0.5 * (1 + math.erf(margin / (SIGMA * math.sqrt(2))))


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def run(start_season=2015):
    rows = elo.load()
    model = elo.Elo()
    recs = []
    for g in rows:
        if g["home_score"] is None:
            model_pred = None
        else:
            model_pred = model.predict(g)
        if model_pred is None:
            continue
        if g["season"] >= start_season and g["spread_line"] is not None:
            actual = g["home_score"] - g["away_score"]
            if actual != 0:
                recs.append({
                    "season": g["season"],
                    "actual": actual,
                    "home_won": 1 if actual > 0 else 0,
                    "model": model_pred,
                    "market": g["spread_line"],
                    "total_line": g["total_line"],
                    "total": g["home_score"] + g["away_score"],
                })
        model.update(g, model_pred)

    n = len(recs)
    model_su = sum(1 for r in recs if (r["model"] > 0) == (r["home_won"] == 1))
    market_su = sum(1 for r in recs if (r["market"] > 0) == (r["home_won"] == 1))
    home_su = sum(r["home_won"] for r in recs)
    agree = sum(1 for r in recs if (r["model"] > 0) == (r["market"] > 0))

    print(f"{n:,} games, {start_season}-{recs[-1]['season']} (ties excluded)\n")
    print("straight-up winner accuracy")
    print(f"  model           {model_su / n:6.1%}")
    print(f"  market favorite {market_su / n:6.1%}   <- the honest comparison")
    print(f"  always home     {home_su / n:6.1%}")
    print(f"  model agrees with the market on the winner: {agree / n:.1%}")

    pm = [win_prob(r["model"]) for r in recs]
    pk = [win_prob(r["market"]) for r in recs]
    y = [r["home_won"] for r in recs]
    base = sum(y) / n
    print("\nwin-probability quality (Brier, lower is better)")
    print(f"  coin flip 0.500 : {brier([0.5] * n, y):.4f}")
    print(f"  base rate {base:.3f} : {brier([base] * n, y):.4f}")
    print(f"  model           : {brier(pm, y):.4f}")
    print(f"  market          : {brier(pk, y):.4f}")

    print("\nmodel calibration by stated confidence")
    buckets = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    for lo, hi in buckets:
        sub = [(p, yy) for p, yy in zip(pm, y)]
        sub = [(max(p, 1 - p), yy if p >= 0.5 else 1 - yy) for p, yy in sub]
        sub = [(p, w) for p, w in sub if lo <= p < hi]
        if sub:
            said = sum(p for p, _ in sub) / len(sub)
            got = sum(w for _, w in sub) / len(sub)
            print(f"  says {lo:.0%}-{hi:.0%}  n={len(sub):5d}  claimed {said:.1%}"
                  f"  actual {got:.1%}")

    mae_m = sum(abs(r["actual"] - r["model"]) for r in recs) / n
    mae_k = sum(abs(r["actual"] - r["market"]) for r in recs) / n
    tot = [r for r in recs if r["total_line"]]
    mae_t = sum(abs(r["total"] - r["total_line"]) for r in tot) / len(tot)
    print("\npoints error (mean absolute)")
    print(f"  model margin   {mae_m:.2f} pts")
    print(f"  market margin  {mae_k:.2f} pts")
    print(f"  market total   {mae_t:.2f} pts  (no model total yet)")

    # A service does not have to choose between its model and the line. The
    # market-anchored blend starts from the line and applies a fraction of the
    # model's disagreement, which is what the regression in elo.py says is
    # defensible.
    print("\nmarket-anchored blend: pred = market + w*(model - market)")
    for w in (0.0, 0.1, 0.2, 0.3, 0.5, 1.0):
        preds = [r["market"] + w * (r["model"] - r["market"]) for r in recs]
        su = sum(1 for p, r in zip(preds, recs) if (p > 0) == (r["home_won"] == 1))
        mae = sum(abs(r["actual"] - p) for p, r in zip(preds, recs)) / n
        bs = brier([win_prob(p) for p in preds], y)
        print(f"  w={w:.1f}  straight-up {su / n:5.1%}  margin MAE {mae:.2f}"
              f"  Brier {bs:.4f}")

    print("\nby season, model straight-up:")
    for season in sorted({r["season"] for r in recs}):
        sub = [r for r in recs if r["season"] == season]
        hit = sum(1 for r in sub if (r["model"] > 0) == (r["home_won"] == 1))
        mk = sum(1 for r in sub if (r["market"] > 0) == (r["home_won"] == 1))
        print(f"  {season}  n={len(sub):3d}  model {hit / len(sub):5.1%}"
              f"   market {mk / len(sub):5.1%}")


if __name__ == "__main__":
    run()
