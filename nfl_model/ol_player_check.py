#!/usr/bin/env python3
"""Audit the lineman ratings against the games they came from.

`ol_player_study.py` produces a rating per lineman and a noise floor. A rating
can clear a noise floor and still be useless, because the test only asks
whether the ratings differ from each other -- not whether they mean the same
thing next year. So this asks the two questions that decide whether the number
is allowed near the model:

* split-half: rate every lineman twice, on two random halves of his own games.
  If the two ratings agree, the rating is measuring the player. If they do not,
  it is measuring which games landed in which pile.
* carryover: rate every lineman on one season, then check whether that rating
  predicts his on/off in the next season. This is the only version of the
  question the model actually faces, because on game day the past is all it
  has.

`--player` prints one lineman's week-by-week log so the rating can be read
against the games instead of taken on faith.
"""
import argparse

import numpy as np
import pandas as pd

from ol_player_study import MIN_OFF, MIN_ON, PRIOR, outcomes, snaps, STARTER

YS = ["sack_rate", "pass_epa", "rush_epa"]


def panel():
    """One row per lineman per team-game, with whether he started it."""
    s = snaps()
    o = outcomes()
    st = s[s.offense_pct >= STARTER]
    roster = st[["season", "team", "player", "pfr_player_id",
                 "position"]].drop_duplicates(
        subset=["season", "team", "pfr_player_id"])
    g = roster.merge(o[["season", "team", "week", "game_id"] + YS],
                     on=["season", "team"], how="inner")
    played = set(zip(st.pfr_player_id, st.game_id))
    g["on"] = [(p, i) in played
               for p, i in zip(g.pfr_player_id, g.game_id)]
    return g


def rate(g, y, min_on=MIN_ON, min_off=MIN_OFF):
    """Shrunk on/off for every lineman with enough games on both sides."""
    out = {}
    for pid, grp in g.groupby("pfr_player_id", sort=False):
        on, off = grp[grp.on], grp[~grp.on]
        if len(on) < min_on or len(off) < min_off:
            continue
        out[pid] = ((on[y].mean() - off[y].mean())
                    * len(on) / (len(on) + PRIOR))
    return pd.Series(out, dtype=float)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--player", help="print this lineman's game log")
    a = ap.parse_args()
    g = panel()

    if a.player:
        p = g[g.player.str.contains(a.player, case=False, na=False)]
        if p.empty:
            raise SystemExit(f"no lineman matching {a.player!r}")
        p = p.sort_values(["season", "week"])
        print(f"{p.player.iloc[0]} -- team blocking, week by week "
              "(all figures already adjusted for opponent and for the "
              "offense's own season baseline)\n")
        print(p[["season", "week", "team", "on"] + YS].to_string(
            index=False, float_format="%.3f"))
        print()
        for y in YS:
            on, off = p[p.on][y], p[~p.on][y]
            print(f"{y:10s} started {on.mean():+.4f} ({len(on)} games)  "
                  f"missed {off.mean():+.4f} ({len(off)} games)  "
                  f"gap {on.mean() - off.mean():+.4f}")
        return

    rng = np.random.default_rng(0)
    half = pd.Series(rng.random(len(g)) < 0.5, index=g.index)
    print("split-half: the same lineman rated on two random halves of his "
          "own games\n")
    for y in YS:
        # Half the games each side, so each half needs half the game minimum.
        x = rate(g[half], y, MIN_ON // 2, MIN_OFF // 2)
        z = rate(g[~half], y, MIN_ON // 2, MIN_OFF // 2)
        both = x.index.intersection(z.index)
        r = np.corrcoef(x[both], z[both])[0, 1]
        print(f"{y:10s} r = {r:+.3f} over {len(both)} linemen")

    print("\nthe same split with the games he missed left whole, so both "
          "halves subtract the same number\n")
    for y in YS:
        x = rate(g[half | ~g.on], y, MIN_ON // 2, MIN_OFF)
        z = rate(g[~half | ~g.on], y, MIN_ON // 2, MIN_OFF)
        both = x.index.intersection(z.index)
        r = np.corrcoef(x[both], z[both])[0, 1]
        print(f"{y:10s} r = {r:+.3f} over {len(both)} linemen "
              "(shared baseline -- agreement here is arithmetic, not skill)")

    print("\ncarryover: rated on one season, checked on the next\n")
    for y in YS:
        pairs = []
        prev = {s: rate(g[g.season == s], y, 4, 2)
                for s in sorted(g.season.unique())}
        for s in sorted(g.season.unique())[:-1]:
            nxt = prev.get(s + 1)
            if nxt is None:
                continue
            both = prev[s].index.intersection(nxt.index)
            pairs += list(zip(prev[s][both], nxt[both]))
        if len(pairs) < 30:
            print(f"{y:10s} too few repeat seasons")
            continue
        arr = np.array(pairs)
        r = np.corrcoef(arr[:, 0], arr[:, 1])[0, 1]
        print(f"{y:10s} r = {r:+.3f} over {len(arr)} season pairs")


if __name__ == "__main__":
    main()
