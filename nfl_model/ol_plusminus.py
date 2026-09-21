#!/usr/bin/env python3
"""Rate linemen play by play instead of game by game.

`ol_player_study.py` compared a team's games with a lineman to its games
without him. That is sixteen games a year per man, and the rating did not
survive being split in half. nflverse participation data lists every player on
the field for every play back to 2016, free, so the same question can be asked
about a thousand plays a year instead: with this man on the field, what happens
to the offence, once the other four linemen, the defence and the offence itself
are accounted for.

That last clause is the whole difficulty and the reason this is a regression
rather than an average. Five linemen are almost always on the field together,
so a good tackle and his mediocre guard get credit for the same plays. Ridge
regression separates them only through the plays where the group changes, and
shrinks everyone toward zero when it cannot tell.

Design: one column per lineman, one per team-season offence, one per defence.

    y (EPA on the play) ~ sum(linemen on field) + offence + defence

solved with an L2 penalty on the lineman columns. The offence column absorbs
"this is the 2023 49ers", so a lineman is measured against his own team's
baseline, not against the league.

Then the same falsification the game-level version failed:

* split-half -- rate each man on a random half of his plays and on the other
  half, and correlate. A real rating agrees with itself.
* carryover -- rate on one season, check the next.
* shuffled -- rerun with the lineman columns permuted within team-season, to
  see how much apparent spread pure noise produces.

If the split-half correlation is near zero again, the answer is that free data
cannot rate a lineman, and more plays was not the missing ingredient.
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsqr

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
OL = {"T", "G", "C", "OL", "OT", "OG"}
MIN_PLAYS = 300   # a lineman needs this many to get a column of his own
RIDGE = 40.0      # L2 on the lineman columns, in units of plays


def positions():
    """gsis_id -> position, for the seasons whose feed omits positions."""
    p = pd.read_csv(os.path.join(DATA, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "position", "display_name"])
    p = p[p.gsis_id.notna()]
    return (dict(zip(p.gsis_id, p.position)),
            dict(zip(p.gsis_id, p.display_name)))


def plays(kind="pass"):
    """One row per play: who was blocking, for whom, against whom, and EPA."""
    pos, name = positions()
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "part_*.parquet"))):
        season = int(f[-12:-8])
        pf = os.path.join(DATA, f"pbp_{season}.csv.gz")
        if not os.path.exists(pf):
            continue
        part = pd.read_parquet(f, columns=["nflverse_game_id", "play_id",
                                           "possession_team",
                                           "offense_players"])
        pbp = pd.read_csv(pf, low_memory=True, usecols=[
            "game_id", "play_id", "season", "week", "posteam", "defteam",
            "play_type", "sack", "epa"])
        pbp = pbp[pbp.play_type == kind]
        d = part.merge(pbp, left_on=["nflverse_game_id", "play_id"],
                       right_on=["game_id", "play_id"], how="inner")
        d = d[d.epa.notna() & d.offense_players.notna()]
        d["ol"] = [tuple(p for p in s.split(";") if pos.get(p) in OL)
                   for s in d.offense_players]
        out.append(d[["season", "week", "game_id", "posteam", "defteam",
                      "epa", "sack", "ol"]])
    return pd.concat(out, ignore_index=True), name


def design(d, ids=None, min_plays=None):
    """Sparse matrix of linemen on the field plus offence and defence columns.

    Returns the matrix, the lineman ids in column order, and how many columns
    at the front of the matrix are linemen (the rest are unpenalised).
    """
    if ids is None:
        cnt = pd.Series([p for row in d.ol for p in row]).value_counts()
        ids = list(cnt[cnt >= (min_plays or MIN_PLAYS)].index)
    idx = {p: i for i, p in enumerate(ids)}
    n_ol = len(ids)
    off = {t: n_ol + i for i, t in enumerate(
        sorted(set(zip(d.season, d.posteam))))}
    dfn = {t: n_ol + len(off) + i for i, t in enumerate(
        sorted(set(zip(d.season, d.defteam))))}
    rows, cols = [], []
    for r, (ol, s, o, v) in enumerate(
            zip(d.ol, d.season, d.posteam, d.defteam)):
        for p in ol:
            if p in idx:
                rows.append(r)
                cols.append(idx[p])
        rows += [r, r]
        cols += [off[(s, o)], dfn[(s, v)]]
    x = sparse.csr_matrix(
        (np.ones(len(rows)), (rows, cols)),
        shape=(len(d), n_ol + len(off) + len(dfn)))
    return x, ids, n_ol


def fit(d, y, ids=None, min_plays=None, ridge=None):
    """Ridge on the lineman columns only; team columns are free."""
    x, ids, n_ol = design(d, ids, min_plays)
    pen = sparse.diags(
        [np.sqrt(ridge or RIDGE)] * n_ol + [0.0] * (x.shape[1] - n_ol))
    a = sparse.vstack([x, pen]).tocsr()
    b = np.concatenate([np.asarray(y, float), np.zeros(x.shape[1])])
    beta = lsqr(a, b, atol=1e-8, btol=1e-8, iter_lim=400)[0]
    return pd.Series(beta[:n_ol], index=ids)


def corr(a, b):
    j = a.index.intersection(b.index)
    if len(j) < 20:
        return np.nan, len(j)
    return float(np.corrcoef(a[j], b[j])[0, 1]), len(j)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", default="pass", choices=["pass", "run"])
    ap.add_argument("--y", default="epa", choices=["epa", "sack"])
    ap.add_argument("--shuffles", type=int, default=3)
    ap.add_argument("--min-plays", type=int, default=MIN_PLAYS)
    ap.add_argument("--ridge", type=float, default=RIDGE)
    ap.add_argument("--out", default="/tmp/ol_plusminus.csv")
    a = ap.parse_args()

    d, name = plays(a.kind)
    d = d.reset_index(drop=True)
    y = d[a.y].astype(float)
    if a.y == "sack":
        y = -y  # so that higher is always better for the offence
    print(f"{len(d):,} {a.kind} plays, {d.season.min()}-{d.season.max()}, "
          f"{len(set(p for r in d.ol for p in r)):,} linemen seen, "
          f"{d.ol.str.len().mean():.2f} identified per play\n")

    def go(dd, yy, mp=None):
        return fit(dd, yy, min_plays=mp or a.min_plays, ridge=a.ridge)

    r = go(d, y)
    print(f"rated {len(r):,} linemen with {a.min_plays}+ plays, "
          f"ridge {a.ridge:g}, "
          f"spread {r.std():.4f} {a.y} per play")

    rng = np.random.default_rng(0)
    floor = []
    for _ in range(a.shuffles):
        sh = d.copy()
        for _, idx in d.groupby(["season", "posteam"]).groups.items():
            sh.loc[idx, "ol"] = pd.Series(
                rng.permutation(d.loc[idx, "ol"].to_numpy()), index=idx)
        floor.append(go(sh, y).std())
    print(f"shuffled spread {np.mean(floor):.4f} +/- {np.std(floor):.4f}"
          f"   -> signal {max(0.0, r.std()**2 - np.mean(floor)**2)**0.5:.4f}")

    half = rng.random(len(d)) < 0.5
    x = go(d[half], y[half], a.min_plays // 2)
    z = go(d[~half], y[~half], a.min_plays // 2)
    c, n = corr(x, z)
    print(f"\nsplit-half   r = {c:+.3f} over {n:,} linemen")

    seasons = sorted(d.season.unique())
    per = {s: go(d[d.season == s], y[d.season == s], 200) for s in seasons}
    xs, zs = [], []
    for s, t in zip(seasons, seasons[1:]):
        j = per[s].index.intersection(per[t].index)
        xs += list(per[s][j])
        zs += list(per[t][j])
    print(f"carryover    r = {np.corrcoef(xs, zs)[0, 1]:+.3f} "
          f"over {len(xs):,} season pairs")

    tab = pd.DataFrame({"player": [name.get(i, i) for i in r.index],
                        a.y: r.values}).sort_values(a.y, ascending=False)
    tab.to_csv(a.out, index=False)
    print(f"\ntop 10\n{tab.head(10).to_string(index=False)}")
    print(f"\nbottom 10\n{tab.tail(10).to_string(index=False)}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
