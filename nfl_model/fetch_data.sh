#!/usr/bin/env bash
# Download the public nflverse data the models read. Free, no credentials.
set -euo pipefail

DIR="${1:-/home/ubuntu/nflmodel/data}"
mkdir -p "$DIR"
BASE=https://github.com/nflverse/nflverse-data/releases/download

curl -fsSL -o "$DIR/games.csv" http://www.habitatring.com/games.csv

# weekly player stats: one combined file through 2024, per-season files after
curl -fsSL -o "$DIR/player_stats.csv" "$BASE/player_stats/player_stats.csv"
for year in 2025 2026; do
  curl -fsSL -o "$DIR/spw_$year.csv" "$BASE/stats_player/stats_player_week_$year.csv"
done

wc -l "$DIR"/*.csv
