"""Snapshot NFL spreads and totals from the-odds-api.com.

DraftKings is the book of record. The other books ride along in the same
request so line_shop.py can find the best number for each side: up to 10
named bookmakers count as one region, so a spreads+totals pull costs 2
credits against the monthly quota whatever the list holds (10 or fewer).
Pinnacle is in the list as the sharp check, not as a book to bet at.
Caesars and Fanatics are paid-plan only on the-odds-api, so they are left out.
Remaining quota is printed from the response headers after every run.

    ODDS_API_KEY=... python3 odds_snapshot.py [--books draftkings,fanduel]
"""

import argparse
import csv
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
import zoneinfo

HOST = "https://api.the-odds-api.com"
SPORT = "americanfootball_nfl"
BOOK_OF_RECORD = "draftkings"
SHARP = "pinnacle"
DEFAULT_BOOKS = ("draftkings", "fanduel", "betmgm", "betrivers", "espnbet",
                 "hardrockbet", SHARP)
MAX_BOOKS = 10  # more than this and the pull costs a second region
FIELDS = ["taken_at_pt", "commence_time", "away", "home", "book",
          "last_update", "spread_line", "total_line",
          "home_spread_price", "away_spread_price", "over_price",
          "under_price"]
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")

TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def fetch(key, books):
    url = (
        f"{HOST}/v4/sports/{SPORT}/odds"
        f"?regions=us&markets=spreads,totals&oddsFormat=american"
        f"&bookmakers={','.join(books)}&apiKey={key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.load(r)
            quota = {
                "remaining": r.headers.get("x-requests-remaining"),
                "used": r.headers.get("x-requests-used"),
            }
    except urllib.error.HTTPError as e:
        sys.exit(f"the-odds-api returned HTTP {e.code}: {e.read().decode()[:300]}")
    return body, quota


def rows(events, books):
    """One row per (game, book), in nflverse's sign convention for spread_line:
    positive means the home team is favored by that many points.
    """
    out = []
    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        for bk in ev.get("bookmakers", []):
            if bk["key"] not in books:
                continue
            spread = total = None
            price = {}
            for mkt in bk.get("markets", []):
                if mkt["key"] == "spreads":
                    for o in mkt["outcomes"]:
                        if o["name"] == home:
                            spread = -float(o["point"])
                            price["home_spread_price"] = o.get("price")
                        elif o["name"] == away:
                            price["away_spread_price"] = o.get("price")
                elif mkt["key"] == "totals":
                    total = float(mkt["outcomes"][0]["point"])
                    for o in mkt["outcomes"]:
                        side = o["name"].lower()
                        if side in ("over", "under"):
                            price[f"{side}_price"] = o.get("price")
            out.append({
                "commence_time": ev["commence_time"],
                "away": TEAM_ABBR.get(away, away),
                "home": TEAM_ABBR.get(home, home),
                "book": bk["key"],
                "last_update": bk["last_update"],
                "spread_line": spread,
                "total_line": total,
                **price,
            })
    return out


def append(path, snap, taken):
    """Append the rows, widening an older file's header first.

    Files written before prices were kept have eight columns; their rows are
    rewritten under the new header with the price columns left blank, so
    every reader (pandas, csv.DictReader) sees one consistent table.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    old, rewrite = [], not os.path.exists(path)
    if not rewrite:
        with open(path, newline="") as fh:
            rd = csv.DictReader(fh)
            if rd.fieldnames != FIELDS:
                old, rewrite = list(rd), True
    if rewrite:
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(old)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        for r in snap:
            w.writerow({"taken_at_pt": taken, **r})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default=",".join(DEFAULT_BOOKS))
    ap.add_argument("--out", default="data/odds_snapshots.csv")
    args = ap.parse_args()

    key = os.environ.get("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY is not set")

    books = [b.strip() for b in args.books.split(",") if b.strip()]
    if len(books) > MAX_BOOKS:
        sys.exit(f"{len(books)} books would cost a second region; "
                 f"keep it to {MAX_BOOKS}")
    events, quota = fetch(key, books)
    snap = rows(events, set(books))
    if not snap:
        sys.exit("no spreads returned -- check the book keys and that games are listed")

    taken = datetime.datetime.now(PACIFIC).isoformat(timespec="seconds")
    append(args.out, snap, taken)

    print(f"snapshot {taken}  {len(snap)} book-lines across {len(events)} games")
    print(f"credits used {quota['used']}, remaining {quota['remaining']}\n")
    missing = [b for b in books if not any(r["book"] == b for r in snap)]
    if missing:
        print(f"no lines from: {', '.join(missing)}\n")

    by_game = {}
    for r in snap:
        by_game.setdefault((r["away"], r["home"]), {})[r["book"]] = r

    print(f"{'game':<12} {'DK':>8} {'total':>7}   other books")
    for (away, home), bybook in sorted(by_game.items()):
        rec = bybook.get(BOOK_OF_RECORD)
        dk = f"{rec['spread_line']:+.1f}" if rec and rec["spread_line"] is not None else "--"
        tot = f"{rec['total_line']:.1f}" if rec and rec["total_line"] is not None else "--"
        others = "  ".join(
            f"{b}{bybook[b]['spread_line']:+.1f}"
            for b in bybook if b != BOOK_OF_RECORD and bybook[b]["spread_line"] is not None
        )
        print(f"{away}@{home:<8} {dk:>8} {tot:>7}   {others}")
    print("\nnflverse sign convention: positive means the home team is favored.")


if __name__ == "__main__":
    main()
