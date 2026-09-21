#!/usr/bin/env bash
# Download the public nflverse data the models read. Free, no credentials.
set -euo pipefail

DIR="${1:-/home/ubuntu/nflmodel/data}"
mkdir -p "$DIR"
BASE=https://github.com/nflverse/nflverse-data/releases/download

curl -fsSL -o "$DIR/games.csv" http://www.habitatring.com/games.csv

# player id crosswalk: the injury feed keys on gsis_id, snap counts on pfr_id
curl -fsSL -o "$DIR/players.csv" "$BASE/players/players.csv"

# weekly player stats: one combined file through 2024, per-season files after
curl -fsSL -o "$DIR/player_stats.csv" "$BASE/player_stats/player_stats.csv"
for year in 2025 2026; do
  curl -fsSL -o "$DIR/spw_$year.csv" "$BASE/stats_player/stats_player_week_$year.csv"
done

# play-by-play (red-zone targets, goal-line carries), snap counts, injury reports
for year in $(seq 2016 2026); do
  curl -fsSL -o "$DIR/pbp_$year.csv.gz" "$BASE/pbp/play_by_play_$year.csv.gz" &
  curl -fsSL -o "$DIR/snap_$year.csv.gz" "$BASE/snap_counts/snap_counts_$year.csv.gz" &
  # injuries are gzipped only for recent seasons
  curl -fsSL -o "$DIR/inj_$year.csv.gz" "$BASE/injuries/injuries_$year.csv.gz" \
    || curl -fsSL -o "$DIR/inj_$year.csv" "$BASE/injuries/injuries_$year.csv" &
done
wait

# who was on the field for each play: 2016-2022 from NGS, 2023 on from FTN,
# published only after the postseason, so the current year is absent
for year in $(seq 2016 2025); do
  curl -fsSL -o "$DIR/part_$year.parquet" \
    "$BASE/pbp_participation/pbp_participation_$year.parquet" &
done
wait

du -sh "$DIR"
