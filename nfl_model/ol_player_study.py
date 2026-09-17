#!/usr/bin/env python3
"""Rate individual linemen, then ask whether the rating is real.

The unit-level study (`ol_study.py`) found continuity worth about 0.066 EPA per
dropback and no penalty at all for a guard playing tackle. Averaging 913
linemen is exactly the wrong way to look for stars, so this does it one player
at a time:

1. For every lineman, compare his own team's blocking outcomes in the games he
   started against the games he missed, *within the same season and team*, so
   the comparison is the same roster and the same coach.
2. Shrink each player's on/off number toward zero by how few games it rests on
   -- a two-game sample is not a rating.
3. Ask whether the spread of those ratings is bigger than chance. A
   permutation test reshuffles who started which games and rebuilds the whole
   table; if the real spread is inside the shuffled spread, the ratings are
   noise with names attached, and nothing here belongs in the model.

Step 3 is the point. Any on/off table on real data produces plausible-looking
stars, and "look, Quenton Nelson grades out well" is not evidence.
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
OL = ("T", "G", "C")
STARTER = 0.5
PRIOR = 24.0   # games of league-average play every rating is shrunk toward
MIN_ON = 8     # a rating needs this many starts and this many misses
MIN_OFF = 4


def snaps():
    cols = ["season", "week", "game_id", "team", "player", "pfr_player_id",
            "position", "offense_pct"]
    fs = sorted(glob.glob(os.path.join(DATA, "snap_*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=cols) for f in fs],
                  ignore_index=True)
    return d[d.position.isin(OL) & d.pfr_player_id.notna()]


def outcomes():
    """Team-game blocking outcomes, residualized for opponent and offense."""
    rows = []
    for f in sorted(glob.glob(os.path.join(DATA, "pbp_*.csv.gz"))):
        p = pd.read_csv(f, low_memory=True, usecols=[
            "game_id", "season", "week", "posteam", "defteam", "play_type",
            "sack", "epa", "run_location", "run_gap"])
        p = p[p.posteam.notna() & p.play_type.isin(["pass", "run"])]
        for (gid, off), g in p.groupby(["game_id", "posteam"], sort=False):
            dp = g[g.play_type == "pass"]
            ru = g[g.play_type == "run"]
            if len(dp) < 10 or len(ru) < 5:
                continue
            inside = ru[ru.run_gap.isin(["guard", "tackle"])]
            rows.append({
                "game_id": gid, "team": off, "def": g.defteam.iloc[0],
                "season": g.season.iloc[0], "week": g.week.iloc[0],
                "sack_rate": dp.sack.mean(), "pass_epa": dp.epa.mean(),
                "rush_epa": ru.epa.mean(),
                "inside_epa": inside.epa.mean() if len(inside) >= 5 else
                np.nan})
    d = pd.DataFrame(rows)
    for y in ("sack_rate", "pass_epa", "rush_epa", "inside_epa"):
        # Subtract the opponent's effect and the offense's own baseline, so
        # what is left is this line, this week, against a neutral defence.
        d[y] = (d[y] - d.groupby("def")[y].transform("mean")
                - d.groupby(["season", "team"])[y].transform("mean")
                + 2 * d[y].mean())
    return d


def table(started, games, ys):
    """On/off per player, within season-team, shrunk toward zero.

    `started` is a boolean Series aligned to `games`, so the permutation test
    can hand in a reshuffled version of exactly the same shape.
    """
    g = games.assign(on=started.values)
    rows = []
    for pid, grp in g.groupby("pfr_player_id", sort=False):
        on, off = grp[grp.on], grp[~grp.on]
        if len(on) < MIN_ON or len(off) < MIN_OFF:
            continue
        r = {"pfr_player_id": pid, "player": grp.player.iloc[0],
             "pos": grp.position.mode().iloc[0],
             "starts": len(on), "missed": len(off)}
        w = len(on) / (len(on) + PRIOR)
        for y in ys:
            r[y] = (on[y].mean() - off[y].mean()) * w
        rows.append(r)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shuffles", type=int, default=25,
                    help="permutation rounds for the noise floor")
    ap.add_argument("--out", default="/tmp/ol_players.csv")
    a = ap.parse_args()
    ys = ["sack_rate", "pass_epa", "rush_epa", "inside_epa"]

    s = snaps()
    o = outcomes()
    # Every game his team played that season, with whether he started it. A
    # lineman who is not in the snap file for a game did not play it.
    st = s[s.offense_pct >= STARTER][
        ["season", "team", "game_id", "player", "pfr_player_id", "position"]]
    roster = st[["season", "team", "player", "pfr_player_id",
                 "position"]].drop_duplicates(
        subset=["season", "team", "pfr_player_id"])
    sched = o[["season", "team", "game_id"] + ys]
    games = roster.merge(sched, on=["season", "team"], how="inner")
    played = set(zip(st.pfr_player_id, st.game_id))
    started = pd.Series(
        [(p, g) in played for p, g in zip(games.pfr_player_id, games.game_id)],
        index=games.index)
    print(f"{len(games):,} player-game rows, "
          f"{games.pfr_player_id.nunique():,} linemen, "
          f"started {started.mean():.1%}")

    t = table(started, games, ys)
    t.to_csv(a.out, index=False)
    print(f"{len(t):,} linemen clear {MIN_ON} starts and {MIN_OFF} misses\n")

    rng = np.random.default_rng(0)
    for y in ys:
        real = t[y].std()
        floor = []
        for _ in range(a.shuffles):
            # Reshuffle who started which games inside each season and team,
            # so every roster keeps its real number of starts and only the
            # names are randomized.
            sh = started.copy()
            for _, idx in games.groupby(["season", "team"]).groups.items():
                sh.loc[idx] = rng.permutation(started.loc[idx].to_numpy())
            floor.append(table(sh, games, [y])[y].std())
        floor = np.array(floor)
        verdict = ("real" if real > floor.mean() + 2 * floor.std()
                   else "inside the noise")
        # What is left after the noise floor is squared out: the spread the
        # ratings would have if the sampling error were removed. This, not
        # the raw spread, is the size of the thing being claimed.
        true = np.sqrt(max(real ** 2 - floor.mean() ** 2, 0.0))
        print(f"{y:11s} spread of ratings {real:.4f}  "
              f"shuffled {floor.mean():.4f} +/- {floor.std():.4f}  "
              f"signal {true:.4f}  -> {verdict}")
        if y == "pass_epa":
            print(f"{'':11s} a one-sigma lineman is worth "
                  f"{true * 35:.2f} EPA over 35 dropbacks, roughly "
                  f"{true * 35:.1f} points of margin")

    print("\nbest and worst by pass protection (sack rate allowed, "
          "negative is good):")
    show = ["player", "pos", "starts", "missed", "sack_rate", "pass_epa",
            "rush_epa", "inside_epa"]
    t = t.sort_values("sack_rate")
    print(t.head(10)[show].to_string(index=False, float_format="%.4f"))
    print(t.tail(10)[show].to_string(index=False, float_format="%.4f"))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
