"""Build a pick sheet after the fact from a week's published scouting notes.

Weeks 9 and 10 of 2026 never got a sheet: only the notes went up, each
committed before Sunday's kickoffs with the model's side on a DraftKings
snapshot. A rerun of the model now would see later data, so the sheet is
rebuilt from what the notes already said, and labeled as posted late.
A game played before the snapshot was taken has no model pick, the same
rule Week 7 used.

Run: python3 late_sheet.py --season 2026 --week 9 --out sheets/2026-w09.html
"""
import argparse
import datetime
import json
import os
import re
import urllib.request
import zoneinfo

import site_chrome

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "picksheet", "template.html")
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
        "scoreboard?seasontype=2&week={week}&dates={season}")
ABBR = {"WSH": "WAS", "LAR": "LA"}


def kickoffs(season, week):
    with urllib.request.urlopen(ESPN.format(season=season, week=week),
                                timeout=30) as r:
        data = json.load(r)
    out = {}
    for ev in data["events"]:
        teams = {c["homeAway"]: ABBR.get(c["team"]["abbreviation"],
                                         c["team"]["abbreviation"])
                 for c in ev["competitions"][0]["competitors"]}
        kick = datetime.datetime.fromisoformat(
            ev["date"].replace("Z", "+00:00")).astimezone(PACIFIC)
        out[f"{teams['away']}@{teams['home']}"] = kick
    return out


def parse_notes(path):
    text = open(path).read()
    snap = re.search(r"DraftKings snapshot of (\d{4}-\d\d-\d\d \d\d:\d\d) PT",
                     text).group(1)
    games = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        away, home = re.match(r"(\w+) @ (\w+)", block).groups()
        line = re.search(r"^line: (\w+) ([-+]?[\d.]+)", block, re.M)
        pick = re.search(r"^pick: (\w+) ([-+][\d.]+)\s*[—-]\s*(.*)$",
                         block, re.M)
        fav, num = line.group(1), float(line.group(2))
        spread = -num if fav == home else num
        team, num = pick.group(1), float(pick.group(2))
        note = pick.group(3).strip()
        games.append(dict(away=away, home=home, spread=spread,
                          devin=f"{team} {'+' if num > 0 else ''}{num:.1f}",
                          devinNote=note,
                          devinDouble=note.upper().startswith("DOUBLE")))
    return snap, games


def build(season, week, notes, out):
    snap, games = parse_notes(notes)
    taken = datetime.datetime.strptime(snap, "%Y-%m-%d %H:%M").replace(
        tzinfo=PACIFIC)
    kicks = kickoffs(season, week)
    rows = []
    for g in games:
        kick = kicks[f"{g['away']}@{g['home']}"]
        row = dict(away=g["away"], home=g["home"], day=kick.strftime("%A"),
                   kick=kick.strftime("%a %-I:%M %p PT"),
                   kickAt=kick.isoformat(), spread=g["spread"], total=None,
                   devin=g["devin"], devinNote=g["devinNote"])
        if kick <= taken:
            row.update(devin="", devinNote="played before the line snapshot"
                       " — no model pick")
        elif g["devinDouble"]:
            row["devinDouble"] = True
        rows.append(row)
    rows.sort(key=lambda r: r["kickAt"])
    slate = f"{season}-w{week:02d}"
    stamp = (f"{taken.strftime('%a %-m/%-d %-I:%M %p')} PT (DraftKings, from "
             f"the Week {week} notes) — sheet posted late, after the games")
    page = open(TEMPLATE).read()
    for key, val in (("__TITLE__", f"{season} Week {week} (posted late)"),
                     ("__SLATE__", slate), ("__TAKEN__", stamp),
                     ("__MAX_STARS__", "2"),
                     ("__GAMES__", json.dumps(rows, indent=2)),
                     ("__CHROME_CSS__", site_chrome.CSS),
                     ("__NAV__", site_chrome.nav("/"))):
        page = page.replace(key, val)
    # Every game is over, so there is no card to send first: show the model.
    page = page.replace("let revealed = false;", "let revealed = true;", 1)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(page)
    return slate, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    notes = os.path.join(ROOT, "notes", f"{a.season}-w{a.week:02d}.md")
    out = a.out or os.path.join(ROOT, "picksheet", "sheets",
                                f"{a.season}-w{a.week:02d}.html")
    slate, rows = build(a.season, a.week, notes, out)
    picks = [r for r in rows if r["devin"]]
    print(f"wrote {out}: {len(rows)} games, {len(picks)} model picks, "
          f"doubles {[r['devin'] for r in rows if r.get('devinDouble')]}")
