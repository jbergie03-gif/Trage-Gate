"""Build per-player-game usage features that separate volume from scoring role.

Season-long carries and targets treat every snap alike, which is why the first
model could not tell a red-zone specialist from a player with the same target
count between the 20s. These are the three inputs that distinguish them:

- red-zone target share    (inside the 20)
- goal-line carry share    (inside the 5)
- offensive snap share

Written to one cached CSV because the play-by-play scan is the slow part.
"""
import glob
import os
import re

import pandas as pd

DATA = "/home/ubuntu/nflmodel/data"
CACHE = f"{DATA}/usage_features.csv"

PBP_COLS = ["season", "week", "season_type", "posteam", "yardline_100", "play_type",
            "rush_attempt", "pass_attempt", "rusher_player_id", "receiver_player_id"]


def norm_name(name):
    name = re.sub(r"[^a-z ]", "", str(name).lower())
    return re.sub(r"\s+(jr|sr|ii|iii|iv)$", "", name).strip()


def redzone_usage():
    """Per player-game: red-zone targets, goal-line carries, and team totals."""
    frames = []
    for path in sorted(glob.glob(f"{DATA}/pbp_*.csv.gz")):
        p = pd.read_csv(path, usecols=PBP_COLS, low_memory=False)
        p = p[(p.season_type == "REG") & p.posteam.notna() & p.yardline_100.notna()]

        rz = p[(p.yardline_100 <= 20) & (p.pass_attempt == 1) & p.receiver_player_id.notna()]
        rz_player = rz.groupby(["season", "week", "posteam", "receiver_player_id"],
                               as_index=False).size().rename(
            columns={"receiver_player_id": "player_id", "size": "rz_targets"})
        rz_team = rz.groupby(["season", "week", "posteam"], as_index=False).size().rename(
            columns={"size": "team_rz_targets"})

        gl = p[(p.yardline_100 <= 5) & (p.rush_attempt == 1) & p.rusher_player_id.notna()]
        gl_player = gl.groupby(["season", "week", "posteam", "rusher_player_id"],
                               as_index=False).size().rename(
            columns={"rusher_player_id": "player_id", "size": "gl_carries"})
        gl_team = gl.groupby(["season", "week", "posteam"], as_index=False).size().rename(
            columns={"size": "team_gl_carries"})

        merged = rz_player.merge(gl_player, on=["season", "week", "posteam", "player_id"],
                                 how="outer")
        merged = (merged.merge(rz_team, on=["season", "week", "posteam"], how="left")
                        .merge(gl_team, on=["season", "week", "posteam"], how="left"))
        frames.append(merged)
    out = pd.concat(frames, ignore_index=True).fillna(
        {"rz_targets": 0, "gl_carries": 0, "team_rz_targets": 0, "team_gl_carries": 0})
    return out.rename(columns={"posteam": "recent_team"})


def snap_shares():
    """Offensive snap percentage, keyed by normalized name + team + week.

    snap_counts uses pfr player ids, not the gsis ids in player_stats, so the
    join goes through the name.
    """
    frames = []
    for pattern in ("snap_*.csv.gz", "snap_*.csv"):
        for path in sorted(glob.glob(f"{DATA}/{pattern}")):
            s = pd.read_csv(path, low_memory=False,
                            usecols=["season", "week", "game_type", "player", "team",
                                     "offense_pct"])
            frames.append(s[s.game_type == "REG"])
    s = pd.concat(frames, ignore_index=True).drop_duplicates(
        ["season", "week", "player", "team"])
    s["name_key"] = s.player.map(norm_name)
    return s.rename(columns={"team": "recent_team", "offense_pct": "snap_pct"})[
        ["season", "week", "recent_team", "name_key", "snap_pct"]]


def build(refresh=False):
    if os.path.exists(CACHE) and not refresh:
        return pd.read_csv(CACHE, low_memory=False)
    rz = redzone_usage()
    rz.to_csv(CACHE, index=False)
    return rz


if __name__ == "__main__":
    rz = build(refresh=True)
    print(f"red-zone/goal-line rows: {len(rz):,}  seasons "
          f"{int(rz.season.min())}-{int(rz.season.max())}")
    print(rz.sort_values("rz_targets", ascending=False).head(5).to_string(index=False))
    s = snap_shares()
    print(f"\nsnap rows: {len(s):,}  seasons {int(s.season.min())}-{int(s.season.max())}")
