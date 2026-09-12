"""Measure how wide and how deep Kalshi's NFL markets actually are, by market type.

Spread width is the entry toll and open interest is whether you can get size on.
Together they say which markets are worth modelling: a market quoted 1c wide with
24k of open interest is efficient and crowded; one quoted 11c wide with no open
interest is soft but untradeable.

Public data, read-only, no credentials.
"""
import json
import statistics
import urllib.request

API = "https://api.elections.kalshi.com/trade-api/v2"

SERIES = [
    ("KXNFLGAME", "game winner"),
    ("KXNFLSPREAD", "game spread"),
    ("KXNFLTOTAL", "game total"),
    ("KXNFLTD", "player anytime/2+ TD"),
    ("KXNFLRSHATT", "player rushing attempts"),
    ("KXNFLFIRSTTD", "player first TD"),
    ("KXNFLLONGRSH", "longest rush"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)


def num(market, key):
    value = market.get(key)
    return float(value) if value not in (None, "") else None


def markets(series, pages=5):
    out, cursor = [], None
    for _ in range(pages):
        url = f"{API}/markets?series_ticker={series}&status=open&limit=200"
        if cursor:
            url += f"&cursor={cursor}"
        page = get(url)
        out += page.get("markets", [])
        cursor = page.get("cursor")
        if not cursor:
            break
    return out


def survey(series, label):
    quoted = []
    for m in markets(series):
        yes_bid = num(m, "yes_bid_dollars")
        no_bid = num(m, "no_bid_dollars")
        if yes_bid is None or no_bid is None:
            continue
        yes_ask = 1 - no_bid
        if yes_bid <= 0 and yes_ask >= 1:  # nothing quoted on either side
            continue
        quoted.append((yes_ask - yes_bid, num(m, "open_interest_fp") or 0.0))
    if not quoted:
        print(f"{label:26s} no quoted markets")
        return
    widths = [w for w, _ in quoted]
    ois = [o for _, o in quoted]
    print(f"{label:26s} n={len(quoted):4d}  median spread={statistics.median(widths)*100:5.1f}c"
          f"  mean={statistics.mean(widths)*100:5.1f}c  median OI={statistics.median(ois):8.0f}")


if __name__ == "__main__":
    for series, label in SERIES:
        try:
            survey(series, label)
        except Exception as exc:  # a dead series shouldn't kill the survey
            print(f"{label:26s} error: {exc}")
