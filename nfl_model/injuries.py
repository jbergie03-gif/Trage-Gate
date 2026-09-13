"""Value-weighted injury burden per team-week.

Counting injured bodies is close to useless: a team can list eight names and
lose nobody who plays. What moves a line is the *snap share* that is missing,
so each player on the report is weighted by the share of his team's snaps he
had been taking before the game in question.

Weights follow how often each designation actually sits: Out is a certainty,
Doubtful nearly so, Questionable usually plays.

The injury feed keys players by gsis_id and the snap feed by pfr_id, so the two
are joined through nflverse's player crosswalk rather than by name.

Snap shares come from prior weeks only, so nothing here uses information that
postdates the game being predicted. Week 1 falls back to last season's share.

Output: data/injury_burden.csv, one row per (season, week, team).
"""
import argparse
import os

import pandas as pd

STATUS_WEIGHT = {"Out": 1.0, "Doubtful": 0.75, "Questionable": 0.25}

# Snap shares are recorded separately for offense and defense, so the side a
# player belongs to decides which column measures his usage.
OFFENSE_POS = {"QB", "RB", "FB", "WR", "TE", "T", "G", "C", "OL", "OT", "OG"}


def side_of(positions):
    return positions.isin(OFFENSE_POS).map({True: "off", False: "def"})


def price_report(inj, snaps):
    """Attach to each injury row the snap share known *going into* that week.

    A player listed Out has no snap row for the game he missed, and one out all
    season has none at all, so this cannot be a join on week: it walks back to
    his most recent cumulative average, then to last season's. Otherwise the
    players who matter most are exactly the ones that go missing.

    Players are keyed by id alone rather than id and team, so a mid-season
    trade keeps the history it earned elsewhere.
    """
    snaps["share"] = snaps["offense_pct"].where(
        snaps["side"] == "off", snaps["defense_pct"])
    played = (snaps.groupby(["season", "gsis_id", "week"])["share"].mean()
              .reset_index().sort_values("week"))
    played["to_date"] = (played.groupby(["season", "gsis_id"])["share"]
                         .transform(lambda s: s.expanding().mean()))

    inj = inj.sort_values("week")
    out = pd.merge_asof(inj, played[["season", "gsis_id", "week", "to_date"]],
                        on="week", by=["season", "gsis_id"],
                        direction="backward", allow_exact_matches=False)

    # Last season's average, for players with no game yet this season.
    last = (played.groupby(["season", "gsis_id"])["share"].mean()
            .rename("last_season").reset_index())
    last["season"] = last["season"] + 1
    out = out.merge(last, on=["season", "gsis_id"], how="left")
    out["prior_share"] = out["to_date"].fillna(out["last_season"])
    return out


def read_years(data, stem, start, end):
    frames = []
    for year in range(start, end + 1):
        for ext in (".csv.gz", ".csv"):
            path = os.path.join(data, f"{stem}_{year}{ext}")
            if os.path.exists(path):
                frames.append(pd.read_csv(path, low_memory=False))
                break
    return pd.concat(frames, ignore_index=True)


def burden(data, start, end):
    inj = read_years(data, "inj", start, end)
    snaps = read_years(data, "snap", start, end)
    xwalk = pd.read_csv(os.path.join(data, "players.csv"), low_memory=False)
    xwalk = xwalk[["gsis_id", "pfr_id"]].dropna().drop_duplicates("pfr_id")

    # game_type is present in every season of the feed; season_type is not.
    snaps = snaps[snaps["game_type"] == "REG"].copy()
    snaps = snaps.merge(xwalk, left_on="pfr_player_id", right_on="pfr_id")
    snaps["side"] = side_of(snaps["position"])

    inj = inj[inj["game_type"] == "REG"].copy()
    inj = inj[inj["report_status"].isin(STATUS_WEIGHT)]
    # The QB is already a first-class model input; double-counting him here
    # would let one absence move the prediction twice.
    inj = inj[inj["position"] != "QB"]
    inj["weight"] = inj["report_status"].map(STATUS_WEIGHT)
    inj["side"] = side_of(inj["position"])

    merged = price_report(inj, snaps)
    matched = merged["prior_share"].notna().mean()
    merged["prior_share"] = merged["prior_share"].fillna(0.0)
    merged["lost"] = merged["weight"] * merged["prior_share"]

    out = (merged.pivot_table(index=["season", "week", "team"], columns="side",
                              values="lost", aggfunc="sum")
           .reset_index().fillna(0.0))
    out = out.rename(columns={"off": "inj_off", "def": "inj_def"})
    for col in ("inj_off", "inj_def"):
        if col not in out.columns:
            out[col] = 0.0
    print(f"{len(out)} team-weeks, {matched:.1%} of report rows priced")
    return out[["season", "week", "team", "inj_off", "inj_def"]]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="/home/ubuntu/nflmodel/data")
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2026)
    a = p.parse_args()

    out = burden(a.data, a.start, a.end)
    path = os.path.join(a.data, "injury_burden.csv")
    out.to_csv(path, index=False)
    print(out.groupby("season")[["inj_off", "inj_def"]].mean().to_string())
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
