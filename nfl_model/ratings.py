"""Walk-forward team and quarterback ratings from per-play efficiency.

Three ideas, all deliberately simple so they can be checked by hand:

1. Opponent-adjusted metrics. A team's offensive rating is what it would do
   against an average defense; the defensive rating is the mirror. After each
   game both move toward the residual -- observed minus what the matchup
   predicted -- which is Elo's update applied to efficiency instead of points.
   Raw per-team ranks (the kind published in weekly stat tables) skip this
   step, so a team that has played three bad defenses looks better than it is.

2. Tendency metrics (pass rate over expectation, neutral pass rate, seconds
   per snap) are the team's own choice, not something an opponent does to
   them, so those are plain exponentially-weighted means with no adjustment.

3. Quarterback ratings are pass EPA per dropback, shrunk toward the league
   mean by career dropbacks, so 40 hot dropbacks do not outrank a season.
   Pass EPA includes the line and the receivers, so this is a QB-anchored
   passing-offense rating rather than a pure quarterback metric. Labeled that
   way on purpose.

Every number a game sees comes from games that finished before it.
"""
import pandas as pd

K = 0.10              # per-game learning rate for opponent-adjusted metrics
K_TEND = 0.15         # learning rate for tendency metrics
SEASON_CARRY = 0.70   # fraction of a rating carried into the next season
QB_CARRY = 0.85
QB_K = 0.08
QB_PRIOR_DB = 150.0   # dropbacks of league-average prior on a new QB
LEAGUE_PASS_EPA = 0.03

# Opponent-adjusted: (column, league mean). The mean only sets the zero point.
ADJUSTED = [
    ("epa_play", 0.0),
    ("epa_pass", 0.03),
    ("epa_rush", -0.04),
    ("success", 0.434),
    ("cpoe", 0.48),
    ("explosive_pass", 0.086),
    ("explosive_rush", 0.114),
]

# Team tendency, not opponent-driven.
TENDENCY = [
    ("plays", 62.4),
    ("proe", -1.37),
    ("neutral_pass_rate", 0.57),
    ("neutral_sec_per_play", 34.6),
]


class Ratings:
    def __init__(self):
        self.off = {m: {} for m, _ in ADJUSTED}
        self.deff = {m: {} for m, _ in ADJUSTED}
        self.tend = {m: {} for m, _ in TENDENCY}
        self.qb = {}
        self.qb_db = {}
        self.season = None

    def new_season(self, season):
        """Regress toward the league mean between seasons (roster turnover)."""
        if self.season is not None and season != self.season:
            for group in (self.off, self.deff, self.tend):
                for m in group:
                    for t in group[m]:
                        group[m][t] *= SEASON_CARRY
            for k in self.qb:
                self.qb[k] *= QB_CARRY
        self.season = season

    # ---- reads (pre-game state) -------------------------------------------
    def o(self, metric, team):
        return self.off[metric].get(team, 0.0)

    def d(self, metric, team):
        return self.deff[metric].get(team, 0.0)

    def t(self, metric, team):
        return self.tend[metric].get(team, 0.0)

    def qb_rating(self, qb_id):
        """Shrunk pass EPA per dropback for a QB, league mean if unseen."""
        db = self.qb_db.get(qb_id, 0.0)
        raw = self.qb.get(qb_id, 0.0)
        return raw * db / (db + QB_PRIOR_DB)

    def qb_seen(self, qb_id):
        return self.qb_db.get(qb_id, 0.0)

    # ---- update (after the game) ------------------------------------------
    def update_game(self, rows):
        """rows: the two team-game rows of one finished game."""
        for r in rows:
            team, opp = r["team"], r["opp"]
            for metric, mean in ADJUSTED:
                val = r.get(metric)
                if val is None or pd.isna(val):
                    continue
                off = self.off[metric].get(team, 0.0)
                dfo = self.deff[metric].get(opp, 0.0)
                resid = (val - mean) - (off - dfo)
                self.off[metric][team] = off + K * resid
                self.deff[metric][opp] = dfo - K * resid

            for metric, mean in TENDENCY:
                val = r.get(metric)
                if val is None or pd.isna(val):
                    continue
                cur = self.tend[metric].get(team, 0.0)
                self.tend[metric][team] = cur + K_TEND * ((val - mean) - cur)

            qb = r.get("qb_id")
            db = r.get("qb_dropbacks") or 0
            if isinstance(qb, str) and db >= 10 and pd.notna(r.get("epa_pass")):
                cur = self.qb.get(qb, 0.0)
                self.qb[qb] = cur + QB_K * ((r["epa_pass"] - LEAGUE_PASS_EPA) - cur)
                self.qb_db[qb] = self.qb_db.get(qb, 0.0) + db
