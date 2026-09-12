"""Live NFL moneyline books from Kalshi and Polymarket, fee-aware.

Both venues are read on executable prices with depth (real order books, not
midpoints). DraftKings Predictions is deliberately absent: it returns HTTP 403
to automated requests and only renders in a browser, so it cannot be polled.

Fee formulas, from primary sources:
  Kalshi taker:     ceil(0.07 * C * P * (1-P))
  Polymarket taker: 0.05 * C * 2 * P * (1-P)        [sports category]
  DraftKings:       tiered per-contract table, per side (not used here)
Makers pay nothing on either venue.
"""

import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

MONTHS = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
          "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}

PM_ABBR = {"ARI": "ari", "ATL": "atl", "BAL": "bal", "BUF": "buf", "CAR": "car", "CHI": "chi",
           "CIN": "cin", "CLE": "cle", "DAL": "dal", "DEN": "den", "DET": "det", "GB": "gb",
           "HOU": "hou", "IND": "ind", "JAC": "jax", "KC": "kc", "LV": "lv", "LAC": "lac",
           "LAR": "lar", "MIA": "mia", "MIN": "min", "NE": "ne", "NO": "no", "NYG": "nyg",
           "NYJ": "nyj", "PHI": "phi", "PIT": "pit", "SF": "sf", "SEA": "sea", "TB": "tb",
           "TEN": "ten", "WAS": "was"}

TEAM_NAMES = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
              "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
              "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
              "HOU": "Texans", "IND": "Colts", "JAC": "Jaguars", "KC": "Chiefs",
              "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins",
              "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
              "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers",
              "SEA": "Seahawks", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}

TICKER_RE = re.compile(r"^KXNFLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]{2,3})([A-Z]{2,3})-([A-Z]{2,3})$")

PM_SPORTS_COEFF = 0.05
KALSHI_COEFF = 0.07


def get_json(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            last = exc
            time.sleep(1.5 * (i + 1))
    raise last


def kalshi_fee(price, contracts):
    """Kalshi taker fee in dollars, rounded up to the next cent."""
    return math.ceil(KALSHI_COEFF * contracts * price * (1 - price) * 100) / 100


def pm_fee(price, contracts):
    """Polymarket sports taker fee in dollars.

    Published table: a 100-lot pays $1.25 at $0.50 and $1.05 at $0.30, which is
    fee = 0.05 * C * 2 * P * (1-P).
    """
    return PM_SPORTS_COEFF * contracts * 2 * price * (1 - price)


def fee(venue, price, contracts):
    return kalshi_fee(price, contracts) if venue == "kalshi" else pm_fee(price, contracts)


def kalshi_games():
    """Open Kalshi NFL game markets keyed by (date, away, home) -> {team: ticker}."""
    games = defaultdict(dict)
    cursor = ""
    while True:
        url = f"{KALSHI}/markets?series_ticker=KXNFLGAME&status=open&limit=200"
        if cursor:
            url += f"&cursor={cursor}"
        data = get_json(url)
        for m in data.get("markets", []):
            match = TICKER_RE.match(m["ticker"])
            if not match:
                continue
            yy, mon, dd, away, home, side = match.groups()
            if not all(t in PM_ABBR for t in (away, home, side)):
                continue
            games[(f"20{yy}-{MONTHS[mon]}-{dd}", away, home)][side] = m["ticker"]
        cursor = data.get("cursor") or ""
        if not cursor or not data.get("markets"):
            break
    return {k: v for k, v in games.items() if len(v) == 2}


def kalshi_book(ticker):
    """Best yes bid/ask in dollars with depth.

    Kalshi keeps one book per market in 'yes'/'no' terms; a 'no' bid at p is an
    offer to sell 'yes' at (1 - p), i.e. the yes ask.
    """
    raw = get_json(f"{KALSHI}/markets/{ticker}/orderbook?depth=10")
    data = raw.get("orderbook_fp") or raw.get("orderbook") or {}
    yes = [(float(p), float(q)) for p, q in (data.get("yes_dollars") or data.get("yes") or [])]
    no = [(float(p), float(q)) for p, q in (data.get("no_dollars") or data.get("no") or [])]
    bid, bid_qty = max(yes) if yes else (None, 0)
    ask, ask_qty = (None, 0)
    if no:
        no_bid, qty = max(no)
        ask, ask_qty = round(1 - no_bid, 4), qty
    return {"bid": bid, "bid_qty": bid_qty, "ask": ask, "ask_qty": ask_qty}


def pm_tokens(date, away, home):
    """Polymarket CLOB token ids for a game's moneyline, {outcome_name: token_id}."""
    for a, b in ((away, home), (home, away)):
        slug = f"nfl-{PM_ABBR[a]}-{PM_ABBR[b]}-{date}"
        try:
            events = get_json(f"{GAMMA}/events?slug={slug}", attempts=1)
        except Exception:
            continue
        if not events:
            continue
        for market in events[0].get("markets", []):
            try:
                outcomes = json.loads(market.get("outcomes") or "[]")
                tokens = json.loads(market.get("clobTokenIds") or "[]")
            except (TypeError, ValueError):
                continue
            if set(outcomes) == {TEAM_NAMES[away], TEAM_NAMES[home]} and len(tokens) == 2:
                return dict(zip(outcomes, tokens))
    return None


def pm_book(token_id):
    data = get_json(f"{CLOB}/book?token_id={token_id}")
    bids = [(float(lv["price"]), float(lv["size"])) for lv in data.get("bids", [])]
    asks = [(float(lv["price"]), float(lv["size"])) for lv in data.get("asks", [])]
    bid, bid_qty = max(bids) if bids else (None, 0)
    ask, ask_qty = min(asks) if asks else (None, 0)
    return {"bid": bid, "bid_qty": bid_qty, "ask": ask, "ask_qty": ask_qty}
