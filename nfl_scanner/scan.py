"""Poll Kalshi and Polymarket NFL moneylines and record every cross-venue gap.

Run once:      python3 scan.py --once
Run forever:   python3 scan.py           (adaptive cadence, see interval())

Records into SQLite: every quote snapshot, every gap, and one row per run so
missed polls are visible rather than silent. Read-only; it never trades.
"""

import argparse
import datetime as dt
import logging
import os
import sys
import time
import zoneinfo

import store
import venues

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SCANNER_DB", os.path.join(HERE, "data", "nfl.sqlite"))
LOG_PATH = os.environ.get("SCANNER_LOG", os.path.join(HERE, "data", "scanner.log"))

# An alert is only interesting if it is both wide enough to survive fees and
# deep enough to be worth the trip.
ALERT_GROSS_CENTS = 2.0
ALERT_SIZE = 100

# Cap the notional we model so a huge book does not imply a huge fill.
MAX_MODEL_SIZE = 500

TOKEN_TTL = 3600  # re-resolve Polymarket slugs hourly, not every poll


def interval(now=None):
    """Seconds until the next poll, denser when prices actually move.

    Gaps open when one venue reprices slower than the other, which means news
    and live play: Sunday inactive reports, and in-game.
    """
    now = now or dt.datetime.now(PACIFIC)
    day, hour = now.weekday(), now.hour  # Mon=0 .. Sun=6
    if day == 6:                                  # Sunday
        if 7 <= hour < 10:
            return 60                             # inactive-report window
        if 10 <= hour < 21:
            return 30                             # live games
    if day in (0, 3) and 17 <= hour < 21:         # MNF / TNF
        return 30
    if day == 5 and 10 <= hour < 21:              # Saturday slate (late season)
        return 120
    if 6 <= hour < 22:
        return 1800                               # daytime baseline
    return 3600


def scan(conn):
    """One full pass. Returns (games, matched, gap_rows)."""
    ts = int(time.time())
    games = venues.kalshi_games()
    matched = 0
    quote_rows = []
    gap_rows = []

    for (date, away, home), tickers in sorted(games.items()):
        tokens = token_cache(date, away, home)
        if not tokens:
            continue
        books = {}
        try:
            for team in (away, home):
                books[team] = {
                    "kalshi": venues.kalshi_book(tickers[team]),
                    "poly": venues.pm_book(tokens[venues.TEAM_NAMES[team]]),
                }
        except Exception as exc:
            logging.warning("book fetch failed for %s@%s: %s", away, home, exc)
            continue
        matched += 1

        for team in (away, home):
            for venue, b in books[team].items():
                quote_rows.append((ts, date, away, home, team, venue,
                                   b["bid"], b["bid_qty"], b["ask"], b["ask_qty"]))

        gap_rows.extend(same_outcome_gaps(ts, date, away, home, books))
        two_sided = two_sided_gap(ts, date, away, home, books)
        if two_sided:
            gap_rows.append(two_sided)

    store.insert_quotes(conn, quote_rows)
    store.insert_gaps(conn, gap_rows)
    conn.commit()
    return len(games), matched, gap_rows


_tokens = {}


def token_cache(date, away, home):
    key = (date, away, home)
    hit = _tokens.get(key)
    if hit and time.time() - hit[0] < TOKEN_TTL:
        return hit[1]
    tokens = venues.pm_tokens(date, away, home)
    _tokens[key] = (time.time(), tokens)
    return tokens


def same_outcome_gaps(ts, date, away, home, books):
    """Buy the same outcome where its ask sits below the other venue's bid."""
    rows = []
    for team in (away, home):
        k, p = books[team]["kalshi"], books[team]["poly"]
        for buy_venue, buy, sell_venue, sell in (
                ("kalshi", k, "poly", p), ("poly", p, "kalshi", k)):
            if not buy["ask"] or not sell["bid"] or sell["bid"] <= buy["ask"]:
                continue
            size = min(buy["ask_qty"], sell["bid_qty"], MAX_MODEL_SIZE)
            if size < 1:
                continue
            gross = (sell["bid"] - buy["ask"]) * size
            fees = (venues.fee(buy_venue, buy["ask"], size)
                    + venues.fee(sell_venue, sell["bid"], size))
            rows.append((ts, date, away, home, "same_outcome",
                         f"{team}: buy {buy_venue} @{buy['ask']:.2f} /"
                         f" sell {sell_venue} @{sell['bid']:.2f}",
                         round((sell["bid"] - buy["ask"]) * 100, 2), size,
                         round(gross - fees, 2)))
    return rows


def two_sided_gap(ts, date, away, home, books):
    """Buy both outcomes at the cheapest ask anywhere; $1.00 settles regardless."""
    legs = []
    for team in (away, home):
        options = [(b["ask"], v, b["ask_qty"]) for v, b in books[team].items() if b["ask"]]
        if not options:
            return None
        legs.append((team,) + min(options))
    total = sum(leg[1] for leg in legs)
    if total >= 1.0:
        return None
    size = min(min(leg[3] for leg in legs), MAX_MODEL_SIZE)
    if size < 1:
        return None
    cost = sum(leg[1] * size for leg in legs)
    fees = sum(venues.fee(leg[2], leg[1], size) for leg in legs)
    detail = " + ".join(f"{t} {v}@{a:.2f}" for t, a, v, _ in legs)
    return (ts, date, away, home, "two_sided", detail,
            round((1.0 - total) * 100, 2), size, round(size - cost - fees, 2))


def alerts(gap_rows):
    return [r for r in gap_rows if r[6] >= ALERT_GROSS_CENTS and r[7] >= ALERT_SIZE]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)])

    conn = store.connect(DB_PATH)
    while True:
        started = time.time()
        error = None
        games = mat = 0
        gap_rows = []
        try:
            games, mat, gap_rows = scan(conn)
        except Exception as exc:
            error = repr(exc)
            logging.exception("scan failed")
        elapsed = round(time.time() - started, 1)
        store.insert_run(conn, (int(started), games, mat, len(gap_rows), elapsed, error))
        conn.commit()

        hits = alerts(gap_rows)
        logging.info("games=%d matched=%d gaps=%d alerts=%d in %ss",
                     games, mat, len(gap_rows), len(hits), elapsed)
        for row in hits:
            logging.warning("ALERT %s %s@%s %s | %.1fc gross, size %d, net $%.2f",
                            row[1], row[2], row[3], row[5], row[6], row[7], row[8])

        if args.once:
            return 0
        time.sleep(max(interval() - elapsed, 5))


if __name__ == "__main__":
    raise SystemExit(main())
