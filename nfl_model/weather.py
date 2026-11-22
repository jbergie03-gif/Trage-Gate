"""Game-time weather forecasts for a slate, logged so they can be graded.

What 2000-2025 says (README section 13): wind and rain push outdoor games
under the closing total, cold and snow on their own do not. Those numbers use
the weather recorded *during* the game, which the line could not see, so the
point of this file is to save the forecast the line *could* see and score the
under lean on that instead.

    python3 weather.py                         # next slate: table + log rows
    python3 weather.py --season 2026 --week 12
    python3 weather.py --notes                 # `weather:` lines for notes/*.md
    python3 weather.py --report                # forecast flags vs O/U results

Forecasts are Open-Meteo's hourly model run at the stadium for the kickoff
hour (free, no key). Every pull appends to the log (--log, else $WEATHER_LOG,
else data/weather_forecasts.csv), one row per game, so a game pulled Thursday
and Saturday has two rows; --report grades the last one before kickoff.
"""
import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
import zoneinfo

import pandas as pd

import game_model
import stadiums

HERE = os.path.dirname(os.path.abspath(__file__))
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
LOG = os.environ.get("WEATHER_LOG",
                     os.path.join(HERE, "data", "weather_forecasts.csv"))
API = "https://api.open-meteo.com/v1/forecast"
HOURLY = ("temperature_2m", "precipitation_probability", "precipitation",
          "snowfall", "wind_speed_10m", "wind_gusts_10m")
FIXED_ROOF = {"dome", "closed"}
# Teams whose roof opens. games.csv leaves `roof` blank for their future games.
RETRACTABLE = {"ARI", "ATL", "DAL", "HOU", "IND"}

# Thresholds from the 2000-2025 study (outdoor games, observed weather).
WIND_UNDER = 15      # mph: 56.7% under (647 games)
WIND_BREEZY = 11     # mph: 11-15 went 55.5% under (945 games)
RAIN_PROB = 50       # % chance in the kickoff hour
COLS = ["pulled_at", "game_id", "season", "week", "kick_pt", "hours_to_kick",
        "roof", "temp_f", "wind_mph", "gust_mph", "precip_prob", "precip_in",
        "snow_in", "flag"]


def host_of(row, games):
    """The team whose stadium the game is in; None for an unmapped neutral site."""
    if row.get("location") != "Neutral" or row.get("stadium") in stadiums.NEUTRAL:
        return row["home_team"]
    home = games[(games.stadium_id == row.get("stadium_id"))
                 & (games.location == "Home")].home_team
    return home.mode().iat[0] if len(home) else None


def roof_of(row, host):
    roof = row.get("roof")
    if isinstance(roof, str) and roof:
        if roof in FIXED_ROOF and host in RETRACTABLE:
            return "retractable"
        return roof
    return "retractable" if host in RETRACTABLE else "outdoors"


def flag(roof, temp, wind, prob, snow):
    """The research in one label. Indoors has no weather to read."""
    if roof in FIXED_ROOF:
        return "indoors"
    out = []
    if wind is not None and wind >= WIND_UNDER:
        out.append(f"lean under: wind {wind:.0f} mph")
    elif wind is not None and wind >= WIND_BREEZY:
        out.append(f"small under lean: wind {wind:.0f} mph")
    if prob is not None and prob >= RAIN_PROB:
        if (snow or 0) > 0 or (temp is not None and temp <= 32):
            out.append("snow likely: no under lean in the history")
        else:
            out.append(f"lean under: rain {prob:.0f}%")
    if not out:
        out.append("no weather effect")
    text = "; ".join(out)
    if roof == "retractable":
        text += " (only if the roof is open)"
    return text


def fetch(lat, lon, kick_utc):
    q = dict(latitude=lat, longitude=lon, hourly=",".join(HOURLY),
             temperature_unit="fahrenheit", wind_speed_unit="mph",
             precipitation_unit="inch", timezone="UTC",
             start_date=kick_utc.date().isoformat(),
             end_date=(kick_utc + dt.timedelta(hours=4)).date().isoformat())
    with urllib.request.urlopen(f"{API}?{urllib.parse.urlencode(q)}",
                                timeout=30) as r:
        h = json.load(r)["hourly"]
    # The kickoff hour and the next three, about the length of a game. Wind is
    # their average, matching the single game-time reading the history used;
    # gusts and rain chance are the worst hour.
    start = kick_utc.replace(minute=0).strftime("%Y-%m-%dT%H:00")
    i = h["time"].index(start)
    win = {k: [v for v in h[k][i:i + 4] if v is not None] for k in HOURLY}
    top = lambda k: max(win[k]) if win[k] else None
    wind = win["wind_speed_10m"]
    return dict(temp_f=win["temperature_2m"][0] if win["temperature_2m"] else None,
                wind_mph=round(sum(wind) / len(wind), 1) if wind else None,
                gust_mph=top("wind_gusts_10m"),
                precip_prob=top("precipitation_probability"),
                precip_in=round(sum(win["precipitation"]), 2),
                snow_in=round(sum(win["snowfall"]), 2))


def slate(season, week):
    g = pd.read_csv(game_model.GAMES)
    return g[(g.season == season) & (g.week == week)].sort_values(
        ["gameday", "gametime"])


def pull(season, week, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    games = pd.read_csv(game_model.GAMES)
    for _, r in slate(season, week).iterrows():
        kick = game_model.kickoff_utc(r).astimezone(dt.timezone.utc)
        host = host_of(r, games)
        roof = roof_of(r, host)
        row = dict(pulled_at=now.astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M"),
                   game_id=r.game_id, season=season, week=week,
                   kick_pt=kick.astimezone(PACIFIC).strftime("%a %-I:%M %p"),
                   hours_to_kick=round((kick - now).total_seconds() / 3600, 1),
                   roof=roof)
        site = host and stadiums.site(host, r.get("stadium"))
        if roof not in FIXED_ROOF and not site and kick > now:
            row["flag"] = f"forecast unavailable (no map spot for {r.get('stadium')})"
        if roof not in FIXED_ROOF and site and kick > now:
            try:
                row.update(fetch(site[0], site[1], kick))
            except Exception as e:  # noqa: BLE001 - one bad game, keep the rest
                row["flag"] = f"forecast unavailable ({type(e).__name__})"
        if "flag" not in row:
            if kick <= now:
                row["flag"] = "already kicked off"
            else:
                row["flag"] = flag(roof, row.get("temp_f"), row.get("wind_mph"),
                                   row.get("precip_prob"), row.get("snow_in"))
        row["match"] = f"{r.away_team} @ {r.home_team}"
        rows.append(row)
    return rows


def log(rows, path=LOG):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new = not os.path.exists(path)
    pd.DataFrame(rows).reindex(columns=COLS).to_csv(
        path, mode="a", header=new, index=False)


def describe(r):
    if r["roof"] in FIXED_ROOF:
        return "indoors"
    if r.get("wind_mph") is None:
        return r["flag"]
    bits = [f"{r['temp_f']:.0f}°F", f"wind {r['wind_mph']:.0f} mph"
            f" (gusts {r['gust_mph']:.0f})", f"rain/snow chance {r['precip_prob']:.0f}%"]
    if r.get("snow_in"):
        bits.append(f"snow {r['snow_in']} in")
    return ", ".join(bits)


def section(rows):
    """Markdown block for the Saturday brief."""
    stamp = rows[0]["pulled_at"] if rows else "-"
    L = [f"## Weather at kickoff (Open-Meteo forecast, pulled {stamp} PT)", "",
         "| Game | Kick (PT) | Roof | Forecast, kickoff + 3 h (wind = average) | Read |",
         "|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['match']} | {r['kick_pt']} | {r['roof']} | "
                 f"{describe(r)} | {r['flag']} |")
    L += ["", "History, 2000-2025 outdoor games vs the closing total: wind 15+ "
          "mph went 56.7% under, rain 61.6%, 25+ mph 81% (39 games); cold or "
          "snow alone showed no under lean. Break-even at -110 is 52.4%. That "
          "history used game-day weather, so these forecast leans are still "
          "being graded (`weather.py --report`); call them leans, not bets."]
    return L


def note_line(r):
    """One `weather:` line for a notes block."""
    if r["roof"] in FIXED_ROOF:
        return "weather: Indoors."
    return f"weather: {describe(r)} at kickoff (forecast). {r['flag'].capitalize()}."


def report(path=LOG):
    """Grade the last forecast before kickoff against the final total."""
    f = pd.read_csv(path)
    f = f[(f.hours_to_kick > 0) & ~f.flag.str.startswith("forecast unavailable")]
    f = f.sort_values("hours_to_kick").drop_duplicates("game_id")
    g = pd.read_csv(game_model.GAMES, usecols=["game_id", "total", "total_line"])
    d = f.merge(g, on="game_id").dropna(subset=["total", "total_line"])
    d = d[d.total != d.total_line]
    if d.empty:
        print("no graded games yet")
        return
    d["under"] = d.total < d.total_line
    d["group"] = d.flag.str.extract(r"^(lean under: \w+|small under lean|"
                                    r"snow likely|no weather effect|indoors)")[0]
    d["pts_vs_line"] = d.total - d.total_line
    out = d.groupby("group").agg(games=("under", "size"),
                                 under_pct=("under", "mean"),
                                 pts_vs_line=("pts_vs_line", "mean"))
    out["under_pct"] = (out.under_pct * 100).round(1)
    out["pts_vs_line"] = out.pts_vs_line.round(1)
    print(out.to_string())
    print("\nbreak-even at -110 is 52.4%; under ~100 games a group is noise")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--notes", action="store_true",
                    help="print a `weather:` line per game for the notes file")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report(a.log)
    season, week = a.season, a.week
    if season is None or week is None:
        season, week = game_model.next_slate(game_model.build(*game_model.load()))
    rows = pull(season, week)
    if not a.no_log:
        log(rows, a.log)
    if a.notes:
        for r in rows:
            print(f"## {r['match']}\n{note_line(r)}\n")
    else:
        print("\n".join(section(rows)))


if __name__ == "__main__":
    main()
