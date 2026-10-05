"""Render the season standings page: Jonathan vs the model, week by week.

Cards come from two places. The model's are filed in
records/devin_cards_2026.json (the sheet as published, doubles marked).
Jonathan's come from the card API on gridironmath.com (/cards), with
records/jonathan_cards_2026.json for weeks he picked elsewhere. Finals come
from the ESPN scoreboard. Each pick is graded on the line it was filed at,
so the two cards can carry different numbers on the same game.

Scoring: 1 point per cover, 2 for a double; pushes void.

Run: python3 standings_build.py [--season S] [--out path] [--cards URL|path]
"""
import argparse
import datetime
import html
import json
import os
import urllib.request
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
        "scoreboard?seasontype=2&week={week}&dates={season}")
CARDS_URL = "https://gridironmath.com/cards"
ALIAS = {"WSH": "WAS", "LAR": "LA"}

CSS = """
body{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:860px;margin:0 auto;padding:20px;background:#121212;color:#e6e6e6}
h1{margin:0 0 4px}h2{margin:28px 0 8px;font-size:20px}
.sub{color:#a8a8a8;margin-bottom:18px}
table{border-collapse:collapse;width:100%;margin-bottom:8px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #2c2c2c;white-space:nowrap}
th{font-size:13px;color:#a8a8a8;text-transform:uppercase;letter-spacing:.03em}
td.n,th.n{text-align:right}
.W{color:#4cd964;font-weight:600}.L{color:#ff6b60;font-weight:600}.P{color:#8a8a8a}
.dbl{font-weight:700}
.total td{font-weight:700;border-top:2px solid #e6e6e6}
.note{color:#a8a8a8;font-size:14px}
a{color:#7ab8ff}
"""


def fetch_json(src):
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=30) as r:
            return json.load(r)
    with open(src) as fh:
        return json.load(fh)


def finals(season, week):
    """{ 'AWAY@HOME': (away, home) } for games that are final."""
    out = {}
    for e in fetch_json(ESPN.format(week=week, season=season))["events"]:
        c = e["competitions"][0]
        if c["status"]["type"]["name"] != "STATUS_FINAL":
            continue
        t = {x["homeAway"]: x for x in c["competitors"]}
        a = ALIAS.get(t["away"]["team"]["abbreviation"], t["away"]["team"]["abbreviation"])
        h = ALIAS.get(t["home"]["team"]["abbreviation"], t["home"]["team"]["abbreviation"])
        out[f"{a}@{h}"] = (int(t["away"]["score"]), int(t["home"]["score"]))
    return out


def grade(game, side, score):
    """W/L/P for `side` like 'CLE +2.5' given (away, home) score."""
    if score is None:
        return None
    team, num = side.split()
    num = float(num)
    away, home = game.split("@")
    a, h = score
    margin = (h - a) if team == home else (a - h)
    adj = margin + num
    return "W" if adj > 0 else "L" if adj < 0 else "P"


def jonathan_cards(src, season, devin):
    """Jonathan's picks per slate from the API, mapped to week by the model's slate list.

    Revisions are merged game by game in submission order: a later card only
    carries the games still open, so its picks override but never erase an
    earlier pick on a locked game."""
    by_slate = {}
    for r in fetch_json(src)["cards"]:
        if r["who"] != "jonathan":
            continue
        picks = by_slate.setdefault(r["slate"], {})
        for p in r["picks"]:
            if p.get("side"):
                picks[p["game"]] = [p["game"], p["side"], bool(p.get("double"))]
    cards = {}
    for week, d in devin.items():
        for s in d["slates"]:
            if s in by_slate:
                cards[week] = list(by_slate[s].values())
    path = os.path.join(HERE, "records", f"jonathan_cards_{season}.json")
    if os.path.exists(path):
        for week, d in fetch_json(path).items():
            cards.setdefault(week, d["picks"])
    return cards


def week_table(week, games, dcard, jcard, scores):
    d = {g: (s, x) for g, s, x in dcard}
    j = {g: (s, x) for g, s, x in jcard} if jcard else {}
    rows, tot = [], {"D": [0, 0, 0, 0], "J": [0, 0, 0, 0]}  # W L P pts
    for g in games:
        sc = scores.get(g)
        cells = [html.escape(g), f"{sc[0]}-{sc[1]}" if sc else "—"]
        for who, card in (("J", j), ("D", d)):
            if g not in card:
                cells += ["", ""]
                continue
            side, dbl = card[g]
            res = grade(g, side, sc)
            label = html.escape(side) + (" ×2" if dbl else "")
            cells.append(f"<span class='{'dbl' if dbl else ''}'>{label}</span>")
            if res is None:
                cells.append("<span class='P'>pending</span>")
            else:
                pts = (2 if dbl else 1) if res == "W" else 0
                tot[who]["WLP".index(res)] += 1
                tot[who][3] += pts
                cells.append(f"<span class='{res}'>{res}{f' +{pts}' if pts else ''}</span>")
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return rows, tot


def rec(t):
    return f"{t[0]}-{t[1]}" + (f"-{t[2]}" if t[2] else "")


def build(season, cards_src):
    devin = fetch_json(os.path.join(HERE, "records", f"devin_cards_{season}.json"))
    jon = jonathan_cards(cards_src, season, devin)
    weeks = sorted(devin, key=int)
    season_rows, sections = [], []
    grand = {"D": [0, 0, 0, 0], "J": [0, 0, 0, 0]}
    for w in weeks:
        dcard = devin[w]["picks"]
        games = [g for g, _, _ in dcard]
        for g, _, _ in jon.get(w, []):
            if g not in games:
                games.append(g)
        scores = finals(season, int(w))
        rows, tot = week_table(w, games, dcard, jon.get(w), scores)
        for k in grand:
            grand[k] = [a + b for a, b in zip(grand[k], tot[k])]
        pending = sum(1 for g in games if g not in scores)
        jnote = "" if w in jon else " — no card from Jonathan"
        season_rows.append(
            f"<tr><td>Week {w}{jnote}</td>"
            f"<td class='n'>{rec(tot['J']) if w in jon else '—'}</td><td class='n'>{tot['J'][3] if w in jon else '—'}</td>"
            f"<td class='n'>{rec(tot['D'])}</td><td class='n'>{tot['D'][3]}</td>"
            f"<td class='n'>{pending or ''}</td></tr>")
        sections.append(
            f"<h2 id='w{w}'>Week {w}</h2>"
            f"<p class='note'>Jonathan {rec(tot['J'])}, {tot['J'][3]} pts · Model {rec(tot['D'])}, {tot['D'][3]} pts"
            + (f" · {pending} game{'s' if pending > 1 else ''} not final" if pending else "") + "</p>"
            "<table><tr><th>Game</th><th>Final</th><th>Jonathan</th><th></th><th>Model</th><th></th></tr>"
            + "".join(rows) + "</table>")
    stamp = datetime.datetime.now(PACIFIC).strftime("%a %b %-d, %-I:%M %p PT")
    lead = "tied" if grand["J"][3] == grand["D"][3] else (
        f"Jonathan leads by {grand['J'][3] - grand['D'][3]}" if grand["J"][3] > grand["D"][3]
        else f"Model leads by {grand['D'][3] - grand['J'][3]}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='dark'>"
            f"<title>Standings — gridironmath</title><style>{CSS}</style></head><body>"
            f"<h1>Jonathan vs the model — {season}</h1>"
            f"<p class='sub'>Against the spread, each pick graded on the line it was filed at. 1 point per cover, 2 for a double, pushes void. {html.escape(lead)}. Updated {stamp}.</p>"
            "<table><tr><th>Week</th><th class='n'>Jonathan</th><th class='n'>Pts</th><th class='n'>Model</th><th class='n'>Pts</th><th class='n'>Open</th></tr>"
            + "".join(season_rows)
            + f"<tr class='total'><td>Season</td><td class='n'>{rec(grand['J'])}</td><td class='n'>{grand['J'][3]}</td>"
              f"<td class='n'>{rec(grand['D'])}</td><td class='n'>{grand['D'][3]}</td><td></td></tr></table>"
            "<p class='note'>The model's record is the product being measured, not an edge claim: it has trailed the closing line on margin error every week.</p>"
            + "".join(sections)
            + "<p><a href='/'>This week's sheet</a> · <a href='/week'>This week's numbers</a></p></body></html>")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--out", default=os.path.expanduser("~/nflmodel/out/standings.html"))
    ap.add_argument("--cards", default=CARDS_URL)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(build(a.season, a.cards))
    print(a.out)
