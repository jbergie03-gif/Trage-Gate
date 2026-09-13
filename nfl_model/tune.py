"""Grid search the rating hyper-parameters on walk-forward error.

The ratings have three knobs (learning rate, between-season carry, QB prior)
and picking them by eye is how you end up fitting the test set. This scores
each combination on out-of-sample margin MAE only, then prints the table so
the choice is visible rather than buried in a constant.
"""
import argparse
import itertools

import game_model as gm
import ratings


def score(g, tg, inj, k, carry, qb_k, qb_prior):
    ratings.K = k
    ratings.SEASON_CARRY = carry
    ratings.QB_K = qb_k
    ratings.QB_PRIOR_DB = qb_prior
    df = gm.build(g, tg, inj)
    p = gm.fit_report(df)
    mae = (p.pred_margin - p.result).abs().mean()
    su = ((p.pred_margin > 0) == (p.result > 0)).mean()
    return mae, su


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="wider grid")
    a = ap.parse_args()

    g, tg, inj = gm.load()
    ks = [0.05, 0.10, 0.15, 0.20, 0.30] if a.full else [0.08, 0.15, 0.25]
    carries = [0.4, 0.55, 0.7, 0.85] if a.full else [0.5, 0.7]
    qbks = [0.08, 0.15, 0.25] if a.full else [0.12]
    priors = [150.0, 320.0, 700.0] if a.full else [320.0]

    best = None
    print(f"{'k':>5s} {'carry':>6s} {'qb_k':>5s} {'qb_prior':>8s} "
          f"{'MAE':>6s} {'SU%':>6s}")
    for k, c, qk, pr in itertools.product(ks, carries, qbks, priors):
        mae, su = score(g, tg, inj, k, c, qk, pr)
        print(f"{k:5.2f} {c:6.2f} {qk:5.2f} {pr:8.0f} {mae:6.3f} {su*100:6.1f}")
        if best is None or mae < best[0]:
            best = (mae, k, c, qk, pr)
    print(f"\nbest MAE {best[0]:.3f} at k={best[1]} carry={best[2]} "
          f"qb_k={best[3]} qb_prior={best[4]}")


if __name__ == "__main__":
    main()
