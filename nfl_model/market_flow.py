"""Where the public is and where the line went, for a slate or a season.

Two separate things get conflated as "sharp money". This pulls both and keeps
them apart:

  public %      - share of spread *tickets* on each side. A crowd count.
  line movement - what the books did about it. The books' own opinion, which
                  is the only one backed by their money.

The interesting case is when they point opposite ways: the public is on one
side and the line moves toward the other anyway, meaning the money arriving
is not the money being counted. That is reverse line movement, and it is the
closest thing to an observable sharp signal in free data.

Tickets are not dollars, so a 75% ticket share can still be a minority of the
handle, and none of these are dollar figures. `--study` grades each cut
against closing lines so the buckets carry a measured rate and a standard
error instead of a reputation.

Source: Sportsbook Review's public consensus page, which serves the whole
table as JSON in its page payload.
"""
import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.request

import pandas as pd

DATA = os.path.expanduser("~/nflmodel/data")
CACHE = os.path.join(DATA, "sbr")
GAMES = os.path.join(DATA, "games.csv")
OUT = os.path.join(DATA, "market_flow.csv")
HIST = os.path.join(DATA, "market_flow_history.csv")
URL = ("https://www.sportsbookreview.com/betting-odds/nfl-football/"
       "consensus/?date={date}")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# The price history interleaves alternate handicaps with the main line: the
# same game shows up at +8.5 for -476 and +14.5 for -1400 within seconds of
# the real number. Read naively, a team's "opening line" comes out four
# points off and every move is invented. The main line is the one priced
# near even money, so anything carrying real juice on either side is an alt.
JUICE = 135

# SBR's abbreviations against nflverse's. Only the disagreements are listed.
TEAMS = {
    "LAR": "LA", "WSH": "WAS", "WAS": "WAS", "JAC": "JAX", "LVR": "LV",
    "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI", "BLT": "BAL",
    "CLV": "CLE", "HST": "HOU",
}

# A line quoted in May is a lookahead number, not an opening number: it is
# priced before free agency has finished settling, let alone the season. The
# opener that means anything is the one hung for the week, so the walk back
# stops at a week out rather than at the first tick ever recorded.
OPEN_LEAD_DAYS = 8


def team(abbr):
    return TEAMS.get(abbr, abbr)


def fetch(date, refresh=False):
    """Cache each date's payload; these pages are 1-15 MB."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{date}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    req = urllib.request.Request(URL.format(date=date), headers={
        "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        html = resp.read().decode("utf-8", "replace")
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S)
    if not m:
        raise RuntimeError(f"no page payload for {date}")
    table = json.loads(m.group(1))["props"]["pageProps"].get(
        "oddsTableModel") or {}
    with open(path, "w") as fh:
        json.dump(table, fh)
    time.sleep(1.5)
    return table


def main_line(history, *fields):
    return [h for h in history
            if all(h.get(f) is not None and abs(h[f]) <= JUICE
                   for f in fields)]


def window(history, kickoff):
    """Open and close, where open is the first quote inside the game's week.

    Earlier than that the number is a lookahead priced before the roster is
    settled, so treating it as an opener turns an offseason guess into a
    week's worth of phantom movement.
    """
    if not history:
        return None, None
    cutoff = kickoff - dt.timedelta(days=OPEN_LEAD_DAYS)
    inside = [h for h in history if pd.Timestamp(h["oddsDate"]) >= cutoff]
    return (inside or history)[0], history[-1]


def across_books(views, kickoff, hist_key, value_key, fields):
    """Median open and close over the books quoting the game.

    One book's feed drops ticks and mislabels the odd alt line as the main
    number; eight books disagreeing by a half point do not all make the same
    mistake at once, so the median is the market's number rather than any
    one shop's.
    """
    opens, closes = [], []
    for view in views:
        hist = main_line(view.get(hist_key) or [], *fields)
        first, last = window(hist, kickoff)
        if first is not None:
            opens.append(first[value_key])
        if last is not None:
            closes.append(last[value_key])

    def med(xs):
        return float(pd.Series(xs).median()) if xs else None

    return med(opens), med(closes), len(closes)


def rows(table, date):
    for row in table.get("gameRows", []):
        game = row["gameView"]
        kickoff = pd.Timestamp(game["startDate"])
        home, away = team(game["homeTeam"]["shortName"]), team(
            game["awayTeam"]["shortName"])
        cons = game.get("consensus") or {}
        views = [o for o in row.get("oddsViews") or [] if o]
        so, sc, books = across_books(
            views, kickoff, "spreadHistory", "homeSpread",
            ("homeOdds", "awayOdds"))
        to, tc, _ = across_books(
            views, kickoff, "totalHistory", "total",
            ("overOdds", "underOdds"))

        # Flipped into nflverse's orientation, where spread_line is positive
        # when the home team is favoured -- the opposite of the handicap a
        # book quotes. So a rising number here means the money came in on the
        # home side, and spread_move reads as "points the home team gained".
        open_spread = None if so is None else -so
        close_spread = None if sc is None else -sc
        move = (None if open_spread is None or close_spread is None
                else close_spread - open_spread)

        yield {
            "kickoff": kickoff,
            "gameday": date,
            "away_team": away,
            "home_team": home,
            "books": books,
            "public_home_pct": cons.get("homeSpreadPickPercent"),
            "public_over_pct": cons.get("overPickPercent"),
            "open_spread": open_spread,
            "close_spread": close_spread,
            "spread_move": move,
            "open_total": to,
            "close_total": tc,
            "total_move": None if to is None or tc is None else tc - to,
        }


def label(r):
    """Name what the two numbers are doing, without editorialising.

    A move is only worth reading when it crosses enough ground to matter and
    the public is lopsided enough to have a side; below that the honest
    label is that nothing happened.
    """
    pub, move = r["public_home_pct"], r["spread_move"]
    if not pub or move is None or abs(move) < 0.5:
        return "flat"
    if abs(pub - 50) < 10:
        return "split public"
    public_home = pub > 50
    money_home = move > 0            # home team gaining points
    if public_home == money_home:
        return "with public"
    return "reverse (home)" if money_home else "reverse (away)"


def collect(games, dates, refresh=False):
    """Scrape the given dates and attach each game's closing line and result.

    Joined on the teams within a day of the scraped date rather than on the
    teams alone: a matchup repeats every season, and a Monday night kickoff
    is already Tuesday in UTC, so the looser join would marry a game to its
    own rematch.
    """
    out = []
    for date in dates:
        try:
            out.extend(rows(fetch(date, refresh), date))
        except Exception as exc:                              # noqa: BLE001
            print(f"  {date}: {exc}")
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["signal"] = df.apply(label, axis=1)
    keys = ["season", "week", "away_team", "home_team", "spread_line",
            "total_line", "result", "total"]
    left = df.assign(_d=pd.to_datetime(df["gameday"])).sort_values("_d")
    right = games.assign(_d=pd.to_datetime(games["gameday"])).sort_values("_d")
    merged = pd.merge_asof(
        left, right[keys + ["_d"]], on="_d",
        by=["away_team", "home_team"], direction="nearest",
        tolerance=pd.Timedelta(days=1))
    return merged.drop(columns=["_d"])


def cover_rate(df, side):
    """Cover rate of `side` against the closing line, pushes dropped.

    Graded on the close, not the open: the close is the number still on the
    board at kickoff, and grading a move against its own starting point
    scores the signal on a price nobody could have taken.
    """
    d = df.dropna(subset=["result", "spread_line"])
    margin = d["result"] - d["spread_line"]        # home team vs the number
    edge = margin if side == "home" else -margin
    played = edge[edge != 0]
    n = len(played)
    return n, (float((played > 0).mean() * 100) if n else float("nan"))


def combined(home_df, away_df):
    """Pool a home-side and an away-side cut into one rate."""
    n_h, r_h = cover_rate(home_df, "home")
    n_a, r_a = cover_rate(away_df, "away")
    n = n_h + n_a
    if not n:
        return 0, float("nan"), float("nan")
    rate = ((r_h * n_h if n_h else 0) + (r_a * n_a if n_a else 0)) / n
    return n, rate, (0.25 / n) ** 0.5 * 100


def study(df):
    """Did backing the public, or fading it, actually cover?"""
    df = df.dropna(subset=["result", "spread_line", "close_spread"]).copy()

    # Games where the scraped close and the graded close disagree by more
    # than a half point are thrown out, and it is not fussiness: whichever
    # of the two numbers is stale is stale *in the direction of the move*,
    # so a mover gets graded against a line it has already left behind and
    # collects points that were never on the board. Left in, they report
    # 78.8% for backing a two-point move, which is not a market inefficiency
    # anyone has ever found -- it is the artifact measuring itself.
    stale = (df["spread_line"] - df["close_spread"]).abs() > 0.5
    print(f"sample: {int((~stale).sum())} games, seasons "
          f"{int(df.season.min())}-{int(df.season.max())}; "
          f"{int(stale.sum())} dropped for disagreeing closing lines")
    df = df[~stale]

    pub = df[df["public_home_pct"].fillna(0) > 0]
    print(f"\nbacking the popular side, by how lopsided the tickets are "
          f"({len(pub)} games priced)")
    for lo, hi in [(50, 55), (55, 60), (60, 65), (65, 70), (70, 101)]:
        home = pub[pub["public_home_pct"].between(lo, hi, "left")]
        away = pub[(100 - pub["public_home_pct"]).between(lo, hi, "left")]
        n, rate, se = combined(home, away)
        if n:
            print(f"  public {lo}-{min(hi, 100)}%: {rate:.1f}% "
                  f"+/-{se:.1f}  (n={n})")

    print("\nbacking the side the line moved toward")
    mv = df.dropna(subset=["spread_move"])
    for lo, hi in [(0.5, 1.0), (1.0, 2.0), (2.0, 99)]:
        n, rate, se = combined(
            mv[mv["spread_move"].between(lo, hi, "left")],
            mv[(-mv["spread_move"]).between(lo, hi, "left")])
        if n:
            print(f"  moved {lo}-{hi} pts: {rate:.1f}% +/-{se:.1f}  (n={n})")

    print("\nreverse line movement: the public on one side, the number "
          "moving the other")
    n, rate, se = combined(df[df["signal"] == "reverse (home)"],
                           df[df["signal"] == "reverse (away)"])
    if n:
        print(f"  backing the move: {rate:.1f}% +/-{se:.1f}  (n={n})")
    for name in ["with public", "split public", "flat"]:
        sub = df[df["signal"] == name]
        n, rate = cover_rate(sub, "home")
        if n:
            se = (0.25 / n) ** 0.5 * 100
            print(f"  {name:13s} home covered {rate:.1f}% +/-{se:.1f} "
                  f"(n={n})   [base rate, no side to take]")

    ovr = df[(df["public_over_pct"].fillna(0) > 0)].dropna(
        subset=["total", "total_line"])
    print(f"\nthe over, by public over% ({len(ovr)} games priced)")
    for lo, hi in [(0, 45), (45, 55), (55, 65), (65, 101)]:
        sub = ovr[ovr["public_over_pct"].between(lo, hi, "left")]
        played = sub[sub["total"] != sub["total_line"]]
        if played.empty:
            continue
        rate = float((played["total"] > played["total_line"]).mean() * 100)
        se = (0.25 / len(played)) ** 0.5 * 100
        print(f"  over {lo}-{min(hi, 100)}%: over hit {rate:.1f}% "
              f"+/-{se:.1f}  (n={len(played)})")


def slate(games, args):
    if args.dates:
        sel = games[games["gameday"].isin(args.dates)]
    elif args.season and args.week:
        sel = games[(games["season"] == args.season)
                    & (games["week"] == args.week)]
    else:
        today = dt.date.today().isoformat()
        ahead = games[games["gameday"] >= today]
        nxt = ahead.iloc[0] if len(ahead) else games.iloc[-1]
        sel = games[(games["season"] == nxt["season"])
                    & (games["week"] == nxt["week"])]
    return args.dates or sorted(sel["gameday"].unique())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", help="YYYY-MM-DD; default next slate")
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--history", nargs="*", type=int,
                    help="seasons to scrape into market_flow_history.csv")
    ap.add_argument("--study", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    games = pd.read_csv(GAMES)

    if args.history:
        done = set()
        if os.path.exists(HIST) and not args.refresh:
            done = set(pd.read_csv(HIST)["gameday"])
        sel = games[games["season"].isin(args.history)]
        sel = sel[sel["game_type"] == "REG"]
        dates = [d for d in sorted(sel["gameday"].unique()) if d not in done]
        print(f"{len(dates)} dates to scrape")
        for i in range(0, len(dates), 10):
            chunk = dates[i:i + 10]
            df = collect(games, chunk, args.refresh)
            if df.empty:
                continue
            df.to_csv(HIST, mode="a", header=not os.path.exists(HIST),
                      index=False)
            print(f"  {chunk[0]}..{chunk[-1]}: +{len(df)} games", flush=True)

    if args.study:
        study(pd.read_csv(HIST))
        return

    df = collect(games, slate(games, args), args.refresh)
    if df.empty:
        print("nothing returned")
        return
    df = df.sort_values("kickoff")

    show = df[["away_team", "home_team", "public_home_pct", "open_spread",
               "close_spread", "spread_move", "public_over_pct",
               "open_total", "close_total", "signal"]]
    print(show.to_string(
        index=False,
        formatters={"public_home_pct": "{:.0f}%".format,
                    "public_over_pct": "{:.0f}%".format,
                    "spread_move": "{:+.1f}".format}))

    if args.save:
        df.to_csv(OUT, index=False)
        print(f"\nwrote {OUT}: {len(df)} games")


if __name__ == "__main__":
    main()
