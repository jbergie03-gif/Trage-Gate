"""Line shopping: the best number for the model's side, with Pinnacle as the check.

The model does not beat the closing line, so the one edge that does not need
it to is a better price than the next bettor gets. odds_snapshot.py already
pulls several books in one request (2 credits however many, up to 10); this
reads the latest snapshot and, for every game the model picks, shows:

- DraftKings, the book of record the sheet and the model's edge use;
- the best number for the model's side at a US book (Pinnacle excluded, it is
  not a book you can bet at in the US), with its price;
- Pinnacle's number: the sharpest line, so the model's edge is also measured
  against it, and a DraftKings number far from it is flagged;
- whether the better number crosses 3 or 7, the margins games land on most.

    python3 line_shop.py                    # next slate, latest snapshot
    python3 line_shop.py --season 2026 --week 12 --odds data/odds_snapshots.csv

Nothing here costs a credit: it reads what odds_snapshot.py wrote.
"""
import argparse
import os

import pandas as pd

import odds_snapshot
import picksheet_build

SHARP = odds_snapshot.SHARP
RECORD = picksheet_build.BOOK
KEYS = (3, 7)
NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
         "betrivers": "BetRivers", "espnbet": "theScore Bet",
         "hardrockbet": "Hard Rock Bet", "pinnacle": "Pinnacle",
         "williamhill_us": "Caesars", "fanatics": "Fanatics"}


def name(book):
    return NAMES.get(book, book)


def snapshot(path=None):
    """Every book's row from the most recent pull, and its time."""
    path = path or picksheet_build.ODDS
    if not os.path.exists(path):
        return pd.DataFrame(), None
    d = pd.read_csv(path)
    if d.empty:
        return d, None
    taken = d["taken_at_pt"].max()
    d = d[d["taken_at_pt"] == taken].copy()
    for c in odds_snapshot.FIELDS:
        if c not in d.columns:
            d[c] = None
    d["_start"] = pd.to_datetime(d["commence_time"], utc=True)
    return d, pd.to_datetime(taken).strftime("%Y-%m-%d %H:%M PT")


def key_share(games, first=2015, last=None):
    """Share of finished games decided by exactly 3 and exactly 7 points."""
    g = games.dropna(subset=["result"])
    g = g[g["season"] >= first]
    if last is not None:
        g = g[g["season"] <= last]
    if g.empty:
        return {}, None
    m = g["result"].abs()
    return ({k: float((m == k).mean()) for k in KEYS},
            (int(g["season"].min()), int(g["season"].max()), len(g)))


def crossed(worse, better):
    """Key margins a move from `worse` to `better` points newly covers.

    For the side's number x (positive = getting points) a finish by margin m
    covers when m + x > 0 and pushes when m + x == 0, so moving x up turns
    every finish with -better <= m <= -worse from a loss or push into a push
    or win. A key number k counts when +k or -k sits in that window.
    """
    if better <= worse:
        return []
    return [k for k in KEYS if worse <= k <= better or worse <= -k <= better]


def price(p):
    if p is None or pd.isna(p):
        return "price n/a"
    p = int(p)
    return f"+{p}" if p > 0 else str(p)


def _num(x):
    return f"{'+' if x > 0 else ''}{x:.1f}" if x else "PK"


def side_lines(game_rows, home):
    """(book, number for the side, price) per book; number in the side's own
    terms, positive when the side is getting points."""
    out = []
    for r in game_rows.itertuples():
        if pd.isna(r.spread_line):
            continue
        n = -float(r.spread_line) if home else float(r.spread_line)
        p = r.home_spread_price if home else r.away_spread_price
        out.append((r.book, n, None if pd.isna(p) else float(p)))
    return out


def best(lines):
    """Most points, then best price; American odds rank by payout as numbers."""
    us = [x for x in lines if x[0] != SHARP]
    if not us:
        return None
    return max(us, key=lambda x: (x[1], -1e9 if x[2] is None else x[2]))


def total_best(game_rows, over):
    us = game_rows[(game_rows["book"] != SHARP) & game_rows["total_line"].notna()]
    if us.empty:
        return None
    col = "over_price" if over else "under_price"
    ranked = sorted(
        ((r.book, float(r.total_line),
          None if pd.isna(getattr(r, col)) else float(getattr(r, col)))
         for r in us.itertuples()),
        key=lambda x: ((-x[1] if over else x[1]),
                       -1e9 if x[2] is None else x[2]))
    return ranked[-1]


def match(snap, g):
    """The snapshot rows for one sheet game: same teams, within three days."""
    kick = pd.Timestamp(g["kickAt"]).tz_convert("UTC")
    m = snap[(snap["away"] == g["away"]) & (snap["home"] == g["home"])
             & ((snap["_start"] - kick).abs() <= pd.Timedelta(days=3))]
    return m


def edge_note(e):
    a = abs(e)
    return "coin flip" if a < 1 else f"{a:.1f}"


def section(games, snap, stamp, shares=None, span=None):
    """Markdown for the brief. `games` from picksheet_build.rows(margins=True)."""
    L = [f"## Line shopping ({stamp or 'no snapshot'}; Pinnacle = sharp check)"]
    if snap.empty:
        return L + ["", "- no odds snapshot on disk; run odds_snapshot.py"]
    books = sorted(snap["book"].unique())
    L += ["", "Books in this snapshot: " + ", ".join(name(b) for b in books)
          + ". Best number = most points for the model's side at a US book "
          "(Pinnacle is left out: it is the check, not a place to bet). "
          "Numbers are from the model's side: + means getting points."]
    if SHARP not in books:
        L += ["", "- **Pinnacle missing from this snapshot**: no sharp check "
              "this week; the Pinnacle columns are blank."]
    L += ["", "| Game | Model side | DraftKings (price) | Best US number (book, price) "
          "| Gain vs DK (pts) | Pinnacle (price) | Model edge vs DK / vs Pinnacle (pts) | Note |",
          "|---|---|---|---|---|---|---|---|"]
    differ = priced = 0
    totals = []
    for g in games:
        if not g.get("devin") or g.get("modelMargin") is None:
            continue
        rows = match(snap, g)
        if rows.empty:
            L.append(f"| {g['away']} @ {g['home']} | {g['devin']} | – | – | – | – | – "
                     "| not in the snapshot |")
            continue
        team = g["devin"].split()[0]
        home = team == g["home"]
        lines = side_lines(rows, home)
        by = {b: (n, p) for b, n, p in lines}
        dk, pin, top = by.get(RECORD), by.get(SHARP), best(lines)
        margin = g["modelMargin"]
        notes = []
        cell_dk = f"{_num(dk[0])} ({price(dk[1])})" if dk else "–"
        cell_pin = f"{_num(pin[0])} ({price(pin[1])})" if pin else "–"
        cell_top = (f"{_num(top[1])} ({name(top[0])}, {price(top[2])})"
                    if top else "–")
        gain = top[1] - dk[0] if top and dk else None
        if gain and gain > 0:
            keys = crossed(dk[0], top[1])
            if keys:
                if dk[1] is not None and top[2] is not None \
                        and top[2] < dk[1]:
                    notes.append(f"costs price: {price(top[2])} vs DK "
                                 f"{price(dk[1])}")
                notes.append("crosses " + " and ".join(
                    f"{k}" + (f" ({shares[k]:.1%} of games end by exactly {k})"
                              if shares and k in shares else "")
                    for k in keys))
        elif gain == 0 and dk and top and top[0] != RECORD:
            if dk[1] is not None and top[2] is not None and top[2] > dk[1]:
                notes.append(f"same number, better price at {name(top[0])}")
        edges = "–"
        if dk:
            # nflverse home-favored convention: spread = -(home side number)
            dk_spread = -dk[0] if home else dk[0]
            e_dk = margin - dk_spread
            edges = edge_note(e_dk)
            if pin:
                priced += 1
                pin_spread = -pin[0] if home else pin[0]
                e_pin = margin - pin_spread
                same = (e_pin > 0) == (e_dk > 0)
                edges += (f" / {edge_note(e_pin)}" if same
                          else f" / {abs(e_pin):.1f} the other way")
                if not same and abs(e_dk) >= 1:
                    notes.append("against Pinnacle the model's side flips")
                elif abs(e_pin) < 1 <= abs(e_dk):
                    notes.append("edge is a coin flip against Pinnacle")
                d = dk[0] - pin[0]
                if d:
                    differ += 1
                    notes.append(f"DK is {abs(d):.1f} {'better' if d > 0 else 'worse'}"
                                 " than Pinnacle for this side")
        L.append(f"| {g['away']} @ {g['home']} | {g['devin']} | {cell_dk} | {cell_top} "
                 f"| {'' if gain is None else (f'{gain:+.1f}' if gain else '0')} | {cell_pin} | {edges} "
                 f"| {'; '.join(notes)} |")
        if g.get("modelTotal") is not None and g.get("total") is not None \
                and g["modelTotal"] != g["total"]:
            over = g["modelTotal"] > g["total"]
            tb = total_best(rows, over)
            pt = rows[rows["book"] == SHARP]["total_line"].dropna()
            totals.append(
                f"| {g['away']} @ {g['home']} | {'Over' if over else 'Under'} "
                f"(model {g['modelTotal']:g}) | {g['total']:g} | "
                + (f"{tb[1]:g} ({name(tb[0])}, {price(tb[2])})" if tb else "–")
                + (f" | {pt.iloc[0]:g} |" if not pt.empty else " | – |"))
    L += ["", f"DraftKings differed from Pinnacle on {differ} of {priced} "
          "games with both lines (model's side)."]
    if shares and span:
        L.append(f"Key numbers ({span[0]}-{span[1]}, {span[2]} games): "
                 + ", ".join(f"{shares[k]:.1%} ended by exactly {k}" for k in KEYS)
                 + ". Half a point across 3 or 7 decides real bets.")
    L += ["", "A better number is worth taking only on a bet you would make "
          "anyway; it does not create an edge. The model's edge vs Pinnacle "
          "is the stricter test: if it is a coin flip there, treat the game "
          "as one."]
    if totals:
        L += ["", "Totals (leans only; the totals model has no demonstrated "
              "O/U edge):", "",
              "| Game | Model lean | DraftKings total | Best US number for the lean "
              "(book, price) | Pinnacle total |", "|---|---|---|---|---|"] + totals
    return L


def main():
    import game_model
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--odds", help="snapshot CSV (default data/odds_snapshots.csv)")
    a = ap.parse_args()
    if a.odds:
        picksheet_build.ODDS = a.odds
    g, tg, inj = game_model.load()
    df = game_model.build(g, tg, inj)
    season, week = a.season, a.week
    if season is None or week is None:
        season, week = game_model.next_slate(df)
    games, _ = picksheet_build.rows(df, season, week, log=False, margins=True)
    snap, stamp = snapshot(a.odds)
    shares, span = key_share(g, last=season - 1)
    print("\n".join(section(games, snap, stamp, shares, span)))


if __name__ == "__main__":
    main()
