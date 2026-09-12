"""Pre-kickoff picks for an upcoming slate, at a stated confidence.

Uses the market-anchored blend that `service_metrics.py` measures as the best
of the available options: start from the closing line, apply a fraction of the
model's disagreement. w=0.15 scored 66.2% straight-up over 3,020 games, versus
66.1% for the line alone and 63.1% for the raw model.

Nothing here is a guaranteed pick. The confidence column is the number the
historical calibration supports, and it is an ordinary probability.
"""
import argparse
import math

import elo
from service_metrics import win_prob

W = 0.15


def upcoming(rows, gameday):
    model = elo.Elo()
    slate = []
    for g in rows:
        if g["home_score"] is None:
            if g["gameday"] == gameday and g["spread_line"] is not None:
                pred = model.predict(g)
                blend = g["spread_line"] + W * (pred - g["spread_line"])
                slate.append({**g, "model": pred, "blend": blend,
                              "p_home": win_prob(blend)})
            continue
        model.update(g, model.predict(g))
    return slate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="gameday, e.g. 2026-09-13")
    a = p.parse_args()

    slate = upcoming(elo.load(), a.date)
    slate.sort(key=lambda g: -abs(g["p_home"] - 0.5))

    print(f"{a.date}: {len(slate)} games   (blend w={W}, line-anchored)\n")
    print(f"{'matchup':<12} {'line':>7} {'model':>7} {'pick':>5} {'conf':>6} "
          f"{'line implies':>13}  disagree")
    for g in slate:
        pick = g["home"] if g["p_home"] > 0.5 else g["away"]
        conf = max(g["p_home"], 1 - g["p_home"])
        mkt = win_prob(g["spread_line"])
        mkt_conf = mkt if g["p_home"] > 0.5 else 1 - mkt
        d = g["model"] - g["spread_line"]
        flag = "  <- model differs" if abs(d) >= 3 else ""
        print(f"{g['away']}@{g['home']:<8} {g['spread_line']:+7.1f} "
              f"{g['model']:+7.1f} {pick:>5} {conf:6.1%} {mkt_conf:12.1%}"
              f"  {d:+5.1f}{flag}")

    print("\ntop 2 by confidence (the double-weight games):")
    for g in slate[:2]:
        pick = g["home"] if g["p_home"] > 0.5 else g["away"]
        conf = max(g["p_home"], 1 - g["p_home"])
        print(f"  {pick} over {g['away'] if pick == g['home'] else g['home']}"
              f"   {conf:.1%}")
    print("\nCalibration says an 80% pick loses 1 game in 5. Not guarantees.")


if __name__ == "__main__":
    main()
