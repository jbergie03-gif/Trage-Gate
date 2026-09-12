"""Home stadium coordinates and timezones, for travel and body-clock features.

Coordinates are the stadium's own latitude/longitude (decimal degrees) and
`tz` is the IANA zone of the venue, which is what a body-clock calculation
needs -- a team's own zone tells us what time their body thinks it is.
Franchises that relocated inside this dataset's window are listed at their
current home; games played at the old venue are a handful of rows and the
distance error is second-order against a 2,000-mile trip.
"""
STADIUM = {
    "ARI": (33.5277, -112.2626, "America/Phoenix"),
    "ATL": (33.7554, -84.4008, "America/New_York"),
    "BAL": (39.2780, -76.6227, "America/New_York"),
    "BUF": (42.7738, -78.7870, "America/New_York"),
    "CAR": (35.2258, -80.8528, "America/New_York"),
    "CHI": (41.8623, -87.6167, "America/Chicago"),
    "CIN": (39.0955, -84.5161, "America/New_York"),
    "CLE": (41.5061, -81.6995, "America/New_York"),
    "DAL": (32.7473, -97.0945, "America/Chicago"),
    "DEN": (39.7439, -105.0201, "America/Denver"),
    "DET": (42.3400, -83.0456, "America/New_York"),
    "GB": (44.5013, -88.0622, "America/Chicago"),
    "HOU": (29.6847, -95.4107, "America/Chicago"),
    "IND": (39.7601, -86.1639, "America/Indiana/Indianapolis"),
    "JAX": (30.3239, -81.6373, "America/New_York"),
    "KC": (39.0489, -94.4839, "America/Chicago"),
    "LA": (33.9535, -118.3392, "America/Los_Angeles"),
    "LAC": (33.9535, -118.3392, "America/Los_Angeles"),
    "LV": (36.0909, -115.1833, "America/Los_Angeles"),
    "MIA": (25.9580, -80.2389, "America/New_York"),
    "MIN": (44.9736, -93.2575, "America/Chicago"),
    "NE": (42.0909, -71.2643, "America/New_York"),
    "NO": (29.9511, -90.0812, "America/Chicago"),
    "NYG": (40.8135, -74.0745, "America/New_York"),
    "NYJ": (40.8135, -74.0745, "America/New_York"),
    "PHI": (39.9008, -75.1675, "America/New_York"),
    "PIT": (40.4468, -80.0158, "America/New_York"),
    "SEA": (47.5952, -122.3316, "America/Los_Angeles"),
    "SF": (37.4030, -121.9698, "America/Los_Angeles"),
    "TB": (27.9759, -82.5033, "America/New_York"),
    "TEN": (36.1665, -86.7713, "America/Chicago"),
    "WAS": (38.9077, -76.8645, "America/New_York"),
    # franchises that moved or share a venue, kept so old game_ids resolve
    "OAK": (37.7516, -122.2005, "America/Los_Angeles"),
    "SD": (32.7831, -117.1196, "America/Los_Angeles"),
    "STL": (38.6327, -90.1885, "America/Chicago"),
}

# Neutral sites that appear in the window, by the venue name in games.csv.
NEUTRAL = {
    "Wembley Stadium": (51.5560, -0.2795, "Europe/London"),
    "Tottenham Hotspur Stadium": (51.6043, -0.0665, "Europe/London"),
    "Twickenham Stadium": (51.4560, -0.3417, "Europe/London"),
    "Estadio Azteca": (19.3029, -99.1505, "America/Mexico_City"),
    "Allianz Arena": (48.2188, 11.6247, "Europe/Berlin"),
    "Deutsche Bank Park": (50.0685, 8.6455, "Europe/Berlin"),
    "Arena Corinthians": (-23.5453, -46.4742, "America/Sao_Paulo"),
    "Santiago Bernabeu": (40.4531, -3.6883, "Europe/Madrid"),
}


def site(home_team, stadium_name=None):
    """Where the game is played: the neutral venue if there is one, else home."""
    if stadium_name and stadium_name in NEUTRAL:
        return NEUTRAL[stadium_name]
    return STADIUM.get(home_team)
