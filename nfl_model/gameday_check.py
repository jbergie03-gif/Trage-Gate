"""Game-day check: who actually plays, read off ESPN's depth charts.

The model and the pick sheet take the quarterback from the schedule feed
(games.csv), which lags reality, and they never look at a depth chart. The
prop and game-script misses that cost the most were backups and goal-line backs
who were not going to play. This reads, for every game still to kick off:

* ESPN's live depth chart (QB, RB, WR1-3, TE, K) with each player's current
  injury tag, cross-checked against nflverse's latest depth-chart snapshot,
* ESPN's game injury report (injury designations; it does not carry the
  official inactive list, which teams post about 90 minutes before kickoff),
* who threw the most passes in each team's last game (ESPN box score),

and reports where the model's assumed quarterback disagrees with any of them,
which starters carry a tag and who is next on the chart, and where every
player on Jonathan's Yahoo roster sits. Each quarterback disagreement comes
with the `input_check.py --swap` command and the what-if number it gives.
Nothing here edits a pick or a published card; it reports, a person decides.

    python3 gameday_check.py                       # this week's unplayed games
    python3 gameday_check.py --season 2026 --week 11 --out gameday.md
    python3 gameday_check.py --roster ~/memory/<bot>/yahoo-fantasy-team.md

Run it Saturday with the brief (weekly_brief.py includes it) and again Sunday
after 8:30 AM PT, when the 10:00 AM inactives are out.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import glob
import json
import os
import re
import time
import urllib.request
import zoneinfo

import pandas as pd

PT = zoneinfo.ZoneInfo("America/Los_Angeles")
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
SCOREBOARD = SITE + "scoreboard?seasontype={stype}&week={week}&dates={season}"
CURRENT = SITE + "scoreboard"
DEPTH = SITE + "teams/{team}/depthcharts"
SUMMARY = SITE + "summary?event={event}"
TEAMS = SITE + "teams"
ABBR = {"WSH": "WAS", "LAR": "LA"}  # ESPN -> nflverse
DATA = os.environ.get("NFL_DATA", "/home/ubuntu/nflmodel/data")

SLOTS = ["qb", "rb", "wr1", "wr2", "wr3", "te", "pk"]
# A tag that can keep a player off the field today. Questionable usually plays,
# but it is exactly what the inactives list settles.
TAGS = ["Out", "Injured Reserve", "Suspension", "Doubtful", "Questionable"]
INACTIVES_BEFORE = dt.timedelta(minutes=90)


def tag_of(status):
    """ESPN marks a player cleared to play as 'Active'; that is no tag."""
    return "" if status in ("", None, "Active") else status


def get(url, tries=2):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 - one retry, then the caller says so
            if i + 1 == tries:
                raise
            time.sleep(2)


def norm(name):
    """'Joe Milton III' and 'Joe Milton' are the same player."""
    s = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " "))
    return " ".join(w for w in s.split() if w not in {"jr", "sr", "ii", "iii", "iv", "v"})


def team(abbr):
    return ABBR.get(abbr, abbr)


REGULAR_WEEKS = 18
# nflverse playoff weeks 19-22 are ESPN postseason weeks 1, 2, 3 and 5 (4 is the Pro Bowl).
PLAYOFF_ESPN = {19: 1, 20: 2, 21: 3, 22: 5}


def espn_week(week):
    """model week -> (ESPN season type, ESPN week)."""
    return (3, PLAYOFF_ESPN[week]) if week > REGULAR_WEEKS else (2, week)


def model_week(stype, week):
    if stype == 3:
        return {v: k for k, v in PLAYOFF_ESPN.items()}.get(week, REGULAR_WEEKS + week)
    return week


def slate(season, week):
    if season is None:
        url = CURRENT
    else:
        stype, w = espn_week(week)
        url = SCOREBOARD.format(stype=stype, season=season, week=w)
    d = get(url)
    games = []
    for ev in d["events"]:
        comp = ev["competitions"][0]
        side = {c["homeAway"]: c for c in comp["competitors"]}
        games.append(dict(
            event=ev["id"],
            away=team(side["away"]["team"]["abbreviation"]),
            home=team(side["home"]["team"]["abbreviation"]),
            away_id=side["away"]["team"]["id"], home_id=side["home"]["team"]["id"],
            kick=dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(PT),
            state=ev["status"]["type"]["state"]))
    year, stype = int(d["season"]["year"]), int(d["season"]["type"])
    return year, model_week(stype, int(d["week"]["number"])), games


def depth_chart(team_id):
    """slot -> [(name, espn_id, tag or '')] in depth order, offense + kicker."""
    out = {}
    for group in get(DEPTH.format(team=team_id)).get("depthchart", []):
        for slot, pos in group["positions"].items():
            if slot not in SLOTS or slot in out:
                continue
            out[slot] = [(a["displayName"], str(a["id"]),
                          tag_of((a.get("injuries") or [{}])[0].get("status")))
                         for a in pos["athletes"]]
    return out


def game_injuries(event):
    """espn_id -> tag from the game's injury report (the inactives on game day)."""
    out = {}
    for t in get(SUMMARY.format(event=event)).get("injuries", []):
        for i in t.get("injuries", []):
            out[str(i["athlete"]["id"])] = tag_of(i.get("status"))
    return out


def passer(event):
    """team -> name of whoever threw the most passes in a finished game."""
    out = {}
    for t in get(SUMMARY.format(event=event))["boxscore"].get("players", []):
        for s in t["statistics"]:
            if s["name"] != "passing" or not s["athletes"]:
                continue
            col = s["keys"].index("completions/passingAttempts")
            best = max(s["athletes"],
                       key=lambda a: int(a["stats"][col].split("/")[1] or 0))
            out[team(t["team"]["abbreviation"])] = best["athlete"]["displayName"]
    return out


def last_passers(season, week, teams):
    """team -> (week, passer) for each team's most recent finished game."""
    found = {}
    for w in range(week, max(week - 4, 0), -1):
        try:
            _, _, games = slate(season, w)
        except Exception:  # noqa: BLE001
            continue
        for g in games:
            if g["state"] != "post" or (g["away"] in found and g["home"] in found):
                continue
            for t, name in passer(g["event"]).items():
                found.setdefault(t, (w, name))
        if all(t in found for t in teams):
            break
    return found


def nflverse_qb1(season, data=DATA):
    """team -> QB1 in nflverse's latest depth-chart snapshot, if downloaded."""
    path = os.path.join(data, f"depth_charts_{season}.csv")
    if not os.path.exists(path):
        return {}, None
    d = pd.read_csv(path, low_memory=False,
                    usecols=["dt", "team", "player_name", "pos_abb", "pos_rank"])
    d = d[d["dt"] == d["dt"].max()]
    q = d[(d["pos_abb"] == "QB") & (d["pos_rank"] == 1)]
    return dict(zip(q["team"], q["player_name"])), d["dt"].max()


def model_qbs(season, week, data=DATA):
    """team -> quarterback the schedule feed (and so the model) assumes."""
    path = os.path.join(data, "games.csv")
    if not os.path.exists(path):
        return {}
    g = pd.read_csv(path)
    g = g[(g["season"] == season) & (g["week"] == week)]
    pairs = list(zip(g["home_team"], g["home_qb_name"])) + \
        list(zip(g["away_team"], g["away_qb_name"]))
    return {t: q for t, q in pairs if pd.notna(q) and str(q).strip()}


def roster(path):
    """[(player, team in the file)] from the Yahoo roster table."""
    rows = []
    if not path or not os.path.exists(path):
        return rows
    for line in open(path):
        m = re.match(r"\|\s*([A-Z/]+)\s*\|\s*([A-Za-z.' -]+?)\s*(?:\([A-Z]+\))?"
                     r"\s*\|\s*([A-Z]*)\s*\|", line)
        if m and m.group(1) != "DEF" and m.group(2).lower() != "player":
            rows.append((m.group(2), m.group(3)))
    return rows


def first_healthy(players, skip=()):
    for name, _, tag in players:
        if name not in skip and tag not in TAGS:
            return name
    return "–"


def fmt(name, tag):
    return f"{name} (**{tag}**)" if tag else name


def check(season=None, week=None, roster_path=None, data=DATA, with_model=True):
    season, week, games = slate(season, week)
    now = dt.datetime.now(PT)
    up = [g for g in games if g["state"] == "pre"]

    with cf.ThreadPoolExecutor(8) as ex:
        all_ids = {team(t["team"]["abbreviation"]): t["team"]["id"]
                   for t in get(TEAMS)["sports"][0]["leagues"][0]["teams"]}
        charts = dict(zip(all_ids, ex.map(depth_chart, all_ids.values())))
        reports = dict(zip([g["event"] for g in up],
                           ex.map(game_injuries, [g["event"] for g in up])))
    # The game report is newer than the depth chart's tag on game day.
    for g in up:
        for side in ("away", "home"):
            for slot, players in charts.get(g[side], {}).items():
                charts[g[side]][slot] = [(n, i, reports[g["event"]].get(i, tag))
                                         for n, i, tag in players]
    assumed = model_qbs(season, week, data)
    nfv, nfv_stamp = nflverse_qb1(season, data)
    last = last_passers(season, week, [g[s] for g in up for s in ("away", "home")])

    L = [f"## Game-day check — {season} week {week} "
         f"(ESPN depth charts, run {now:%a %Y-%m-%d %H:%M} PT)", ""]
    if not up:
        return L + ["No games left to kick off this week."]
    L += ["| Game | Kick (PT) | Inactives due ~ | Run after that time? |", "|---|---|---|---|"]
    for g in sorted(up, key=lambda g: g["kick"]):
        due = g["kick"] - INACTIVES_BEFORE
        L.append(f"| {g['away']} @ {g['home']} | {g['kick']:%a %-I:%M %p} | "
                 f"{due:%a %-I:%M %p} | {'yes' if now >= due else '**no — rerun after**'} |")
    L += ["", "Tags below are injury designations (ESPN depth charts and game injury "
          "reports), not the official inactive list: a healthy scratch has no tag, so "
          "after the time above confirm a flagged player on the team's posted inactives."]
    L += ["", "Sources: ESPN team depth charts and game injury reports (live), "
          f"nflverse depth charts ({nfv_stamp or 'not downloaded'}), ESPN box "
          "scores for last game's passer; the model's QB is games.csv.", ""]

    # ---- quarterbacks ------------------------------------------------------
    L += ["### Quarterbacks", "",
          "| Game | Team | Model assumes | ESPN QB1 | nflverse QB1 "
          "| Threw most passes last game | Flag |",
          "|---|---|---|---|---|---|---|"]
    swaps, maybes = [], []
    for g in sorted(up, key=lambda g: g["kick"]):
        for side in ("away", "home"):
            t = g[side]
            qbs = charts.get(t, {}).get("qb", [])
            if not qbs:
                L.append(f"| {g['away']} @ {g['home']} | {t} | {assumed.get(t, '?')} | "
                         "no ESPN depth chart | | | **unverified** |")
                continue
            qb1, _, tag = qbs[0]
            starter = qb1 if tag not in TAGS[:4] else first_healthy(qbs, {qb1})
            flags = []
            if tag:
                nxt = first_healthy(qbs, {qb1})
                flags.append(f"QB1 tagged {tag}; next healthy: {nxt}")
                if starter == qb1 and nxt != "–":
                    maybes.append((t, nxt))
            model = assumed.get(t)
            if model and norm(model) != norm(starter):
                flags.append(f"**model has the wrong QB** — rerun with {starter}")
                swaps.append((t, starter))
            if t in nfv and norm(nfv[t]) != norm(qb1):
                flags.append(f"depth charts disagree (nflverse: {nfv[t]})")
            was = last.get(t)
            if was and norm(was[1]) != norm(starter):
                flags.append(f"new starter: {was[1]} threw most in week {was[0]}")
            L.append(f"| {g['away']} @ {g['home']} | {t} | {model or '?'} | {fmt(qb1, tag)} | "
                     f"{nfv.get(t, '–')} | {was[1] + f' (wk {was[0]})' if was else '–'} | "
                     f"{'; '.join(flags) or 'ok'} |")
    L.append("")
    cmd = "    python3 input_check.py --season {} --week {} --swap {}=\"{}\""
    if swaps:
        L += ["Rerun each flagged game with the ESPN starter before using its number "
              "(Betting, Pick'em, notes):", ""]
        L += [cmd.format(season, week, t, n) for t, n in swaps] + [""]
    if maybes:
        L += ["If a Questionable/Doubtful QB1 sits (check the inactives), the game "
              "becomes:", ""]
        L += [cmd.format(season, week, t, n) for t, n in maybes] + [""]
    if with_model and (swaps or maybes):
        L += what_if(season, week, swaps + maybes, data)

    # ---- skill-position starters with a tag ---------------------------------
    L += ["### Starters with an injury tag (who is next on the chart)", "",
          "| Game | Team | Spot | Starter | Tag | Next healthy on chart |",
          "|---|---|---|---|---|---|"]
    n = 0
    for g in sorted(up, key=lambda g: g["kick"]):
        for side in ("away", "home"):
            for slot in SLOTS[1:]:
                players = charts.get(g[side], {}).get(slot, [])
                if players and players[0][2]:
                    n += 1
                    L.append(f"| {g['away']} @ {g['home']} | {g[side]} | {slot.upper()} | "
                             f"{players[0][0]} | {players[0][2]} | "
                             f"{first_healthy(players, {players[0][0]})} |")
    if not n:
        L.append("| – | – | – | no RB/WR/TE/K starter carries a tag | | |")
    L.append("")

    # ---- Jonathan's roster --------------------------------------------------
    mine = roster(roster_path)
    if mine:
        kick = {g[s]: g for g in games for s in ("away", "home")}
        L += ["### Jonathan's roster on the depth charts", "",
              "| Player | Team (ESPN) | Spot | Tag | Kick (PT) | Note |",
              "|---|---|---|---|---|---|"]
        for name, listed in mine:
            hit = [(t, slot, i + 1, tag) for t, ch in charts.items()
                   for slot, ps in ch.items() for i, (p, _, tag) in enumerate(ps)
                   if norm(p) == norm(name)]
            if not hit:
                L.append(f"| {name} | – | not on an offense depth chart | | | **check status** |")
                continue
            t, slot, rank, tag = hit[0]
            g = kick.get(t)
            notes = []
            if listed and listed != t:
                notes.append(f"roster file says {listed}")
            if g is None:
                when = "bye"
            elif g["state"] != "pre":
                when = "played"
            else:
                when = f"{g['kick']:%a %-I:%M %p}"
                if tag in TAGS or rank > 1:
                    notes.append(f"recheck after {g['kick'] - INACTIVES_BEFORE:%-I:%M %p}")
            nth = {1: "1st", 2: "2nd", 3: "3rd"}.get(rank, f"{rank}th")
            L.append(f"| {name} | {t} | {slot.upper()}, {nth} on chart | {tag or '–'} | {when} | "
                     f"{'; '.join(notes)} |")
        L.append("")

    L += ["What this cannot check: a player who is active but limited (snap "
          "counts come after the game), and late scratches after the inactives "
          "post. Depth charts are team-published and ESPN-maintained; a "
          "disagreement with nflverse or last week's box score means look at "
          "team news before trusting either.", ""]
    return L


def what_if(season, week, swaps, data):
    try:
        import input_check
        lines = input_check.check(season, week, data, swaps)
    except Exception as e:  # noqa: BLE001 - the check still reads without it
        return [f"- what-if rerun failed: {e!r}", ""]
    out = [ln for ln in lines if ln.startswith(("- could not find", "- ")) and
           ("with" in ln and "home margin" in ln or ln.startswith("- could not"))]
    return (["What-if (input_check.py, home margin vs the nflverse line):", ""]
            + out + [""]) if out else []


def default_roster():
    flat = os.path.expanduser("~/memory/yahoo-fantasy-team.md")
    nested = sorted(glob.glob(os.path.expanduser("~/memory/*/yahoo-fantasy-team.md")))
    return flat if os.path.exists(flat) or not nested else nested[0]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int)
    p.add_argument("--week", type=int)
    p.add_argument("--roster", default=default_roster())
    p.add_argument("--data", default=DATA)
    p.add_argument("--no-model", action="store_true",
                   help="skip the input_check what-if reruns")
    p.add_argument("--out")
    a = p.parse_args()
    text = "\n".join(check(a.season, a.week, a.roster, a.data, not a.no_model))
    print(text)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
