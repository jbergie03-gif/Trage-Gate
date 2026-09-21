"""Move the model's margin by Fantasy Guru's offensive-line advantage.

Jonathan asked for this knowing what it is. Read this before trusting a number
it produced.

Every other feature in this model earned its coefficient by being fit on
completed games. This one cannot: Fantasy Guru's SMASH pages overwrite
themselves weekly and keep no archive, so on the day this was written there was
exactly one snapshot on disk and nothing to fit against. The size below is a
hand-set prior, not a measurement:

  The missing-starter work measured a team losing one full-time starting
  lineman at about 1.6 points of margin. A one-standard-deviation gap in line
  quality between two teams is a smaller thing than that, and `smash_check.py`
  found their game-level advantage already agrees with the closing spread at
  r=+0.51 -- so most of it is priced and only the remainder can be ours to add.
  Half a point per standard deviation, capped at a point and a half, is
  deliberately at the low end of defensible.

So the adjustment is small, capped, always reported separately, and logged
beside the unadjusted number. That log is the point: by around week 13 there
are enough weeks on disk to score adjusted against unadjusted out of sample and
either fit the real coefficient or switch this off. Until then a printed number
is a labelled guess.

    python3 smash_feature.py --season 2026 --week 3      # what it would move
    python3 smash_feature.py --points-per-sd 0            # off, same code path
"""
import argparse
import datetime
import glob
import os
import zoneinfo

import pandas as pd

DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")
FG = os.path.expanduser(os.environ.get("FG_OUT", "~/fgdata"))
LOG = os.path.join(DATA, "smash_log.csv")

POINTS_PER_SD = float(os.environ.get("SMASH_POINTS_PER_SD", "0.5"))
CAP = float(os.environ.get("SMASH_CAP", "1.5"))

# Their matchups page spells four teams differently from nflverse. Silently
# dropping one is how a game quietly stops being adjusted, so `apply` counts
# what matched and `main` prints it.
CODE = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "LVR": "LV"}

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def snapshots():
    """Every dated SMASH snapshot with a matchups table, newest last."""
    found = sorted(glob.glob(os.path.join(FG, "smash", "*", "matchups.csv")))
    return [(os.path.basename(os.path.dirname(p)), p) for p in found]


def advantage(path=None):
    """Home-minus-away offensive-line advantage per matchup, in their units.

    Returns the empty frame when there is no snapshot, so a caller that has
    never run the puller keeps the plain model rather than crashing.
    """
    if path is None:
        have = snapshots()
        if not have:
            return pd.DataFrame(columns=["away", "home", "adv", "as_of"])
        as_of, path = have[-1]
    else:
        as_of = os.path.basename(os.path.dirname(path))
    m = pd.read_csv(path)
    m["away"] = m["AWAY"].replace(CODE)
    m["home"] = m["HOME"].replace(CODE)
    m["adv"] = m["O-LINE ADV (HOME)"] - m["O-LINE ADV (AWAY)"]
    m["as_of"] = as_of
    return m[["away", "home", "adv", "as_of"]]


def points(adv, points_per_sd=None, cap=None):
    """Their advantage as points of home margin, standardised and capped.

    Standardised within the slate because the scale is proprietary and
    undocumented: a raw 40 means nothing on its own, whereas being the widest
    line mismatch of the week is a statement we can size.
    """
    pps = POINTS_PER_SD if points_per_sd is None else points_per_sd
    lid = CAP if cap is None else cap
    sd = adv.std(ddof=0)
    if not sd or pd.isna(sd):
        return adv * 0.0
    return (pps * (adv - adv.mean()) / sd).clip(-lid, lid)


def apply(slate, points_per_sd=None, cap=None, path=None):
    """Add `smash_adj` and shift `pred_margin`, keeping the original.

    `pred_margin_plain` is the model as it was before this file existed. Every
    caller can therefore report both, and the log can score both later.
    """
    slate = slate.copy()
    slate["pred_margin_plain"] = slate["pred_margin"]
    slate["smash_adj"] = 0.0
    slate["smash_as_of"] = None
    adv = advantage(path)
    if adv.empty:
        return slate
    key = dict(zip(zip(adv.away, adv.home), adv.adv))
    matched = pd.Series(
        [key.get((a, h)) for a, h in zip(slate.away_team, slate.home_team)],
        index=slate.index, dtype=float)
    if matched.notna().sum() < 2:
        # One game cannot be standardised against its own slate.
        return slate
    adjusted = points(matched.dropna(), points_per_sd, cap)
    slate.loc[adjusted.index, "smash_adj"] = adjusted
    slate["pred_margin"] = slate["pred_margin_plain"] + slate["smash_adj"]
    slate["smash_as_of"] = adv["as_of"].iloc[0]
    return slate


def log(slate, season, week, path=LOG):
    """Append both numbers so the adjustment can be scored once weeks pile up.

    Written every build, one row per game per snapshot date. Re-running a build
    appends again on purpose: the rows are a record of what was published when,
    not a table to be kept unique.
    """
    if "smash_adj" not in slate:
        return None
    rows = pd.DataFrame({
        "logged_at": datetime.datetime.now(PACIFIC).isoformat(
            timespec="seconds"),
        "season": season, "week": week,
        "smash_as_of": slate["smash_as_of"],
        "away": slate["away_team"], "home": slate["home_team"],
        "spread_line": slate["spread_line"],
        "pred_margin_plain": slate["pred_margin_plain"].round(2),
        "smash_adj": slate["smash_adj"].round(2),
        "pred_margin": slate["pred_margin"].round(2),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows.to_csv(path, mode="a", header=not os.path.exists(path), index=False)
    return path


def score(path=LOG, games=None):
    """Compare the nudged number against the plain one on games since played.

    The whole justification for a hand-set size is that this eventually says
    whether it helped. One row per game is taken -- the earliest log entry for
    it, which is the number that was actually published before kickoff.
    """
    if not os.path.exists(path):
        return None
    g = pd.read_csv(games or os.path.join(DATA, "games.csv"),
                    usecols=["season", "week", "away_team", "home_team",
                             "home_score", "away_score", "spread_line"])
    g = g[g["home_score"].notna()]
    g["result"] = g["home_score"] - g["away_score"]
    d = pd.read_csv(path).sort_values("logged_at")
    d = d.drop_duplicates(["season", "week", "away", "home"], keep="first")
    m = d.merge(g.rename(columns={"away_team": "away", "home_team": "home"}),
                on=["season", "week", "away", "home"],
                how="inner", suffixes=("", "_g"))
    if m.empty:
        return None
    out = {"n": len(m)}
    for name, col in (("plain", "pred_margin_plain"), ("smash", "pred_margin")):
        live = m[m["result"] != m["spread_line"]]
        out[f"{name}_mae"] = (m[col] - m["result"]).abs().mean()
        out[f"{name}_ats"] = (((live[col] - live["spread_line"])
                               * (live["result"] - live["spread_line"]) > 0)
                              .mean() if len(live) else None)
    return out


def main():
    import game_model

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--points-per-sd", type=float, default=POINTS_PER_SD)
    ap.add_argument("--cap", type=float, default=CAP)
    ap.add_argument("--snapshot", help="a matchups.csv to use instead of the "
                                       "newest one on disk")
    ap.add_argument("--score", action="store_true",
                    help="score the log against results instead")
    a = ap.parse_args()

    if a.score:
        s = score()
        if not s:
            print("nothing in the log has been played yet")
            return
        print(f"{s['n']} logged games played")
        for name in ("plain", "smash"):
            ats = s[f"{name}_ats"]
            print(f"  {name:6s} margin MAE {s[f'{name}_mae']:.2f}"
                  + (f"   ATS {ats:.1%}" if ats is not None else ""))
        return

    have = snapshots()
    print(f"{len(have)} snapshots on disk"
          + (f", newest {have[-1][0]}" if have else ""))
    if len(have) < 10:
        print(f"{10 - len(have)} more weeks before this can be scored out of "
              "sample; until then the size below is a prior, not a fit")

    df = game_model.build(*game_model.load())
    season, week = (a.season, a.week)
    if season is None or week is None:
        season, week = game_model.next_slate(df)
    slate = apply(game_model.predict_slate(df, season, week),
                  a.points_per_sd, a.cap, a.snapshot)
    if slate.empty:
        print("no slate with a posted line")
        return
    print(f"\n{season} week {week}   {a.points_per_sd} pts per sd, "
          f"cap {a.cap}\n")
    print(f"{'game':<10} {'line':>6} {'plain':>7} {'smash':>7} {'final':>7}"
          f"  {'edge':>6}")
    for r in slate.itertuples():
        print(f"{r.away_team}@{r.home_team:<6} {r.spread_line:+6.1f} "
              f"{r.pred_margin_plain:+7.1f} {r.smash_adj:+7.2f} "
              f"{r.pred_margin:+7.1f}  {r.pred_margin - r.spread_line:+6.1f}")
    adv = advantage(a.snapshot)
    pairs = set(zip(adv.away, adv.home))
    missing = [f"{r.away_team}@{r.home_team}" for r in slate.itertuples()
               if (r.away_team, r.home_team) not in pairs]
    if missing:
        print(f"not on their matchups page: {', '.join(missing)}")
    moved = (slate["smash_adj"].abs() > 0.01).sum()
    flips = ((slate["pred_margin_plain"] - slate["spread_line"] > 0)
             != (slate["pred_margin"] - slate["spread_line"] > 0)).sum()
    print(f"\n{moved} of {len(slate)} games moved, {flips} changed side "
          f"of the line")


if __name__ == "__main__":
    main()
