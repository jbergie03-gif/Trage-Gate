"""Compare the anytime-TD model against Kalshi's live anytime-TD books.

Prints the largest disagreements. This is a research output, not a pick list:
every player here still needs an inactive/depth-chart check before the number
means anything, because the model happily projects a player who isn't dressed.
"""
import re
import urllib.request
import json

import numpy as np
import pandas as pd

import td_model

API = "https://api.elections.kalshi.com/trade-api/v2"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)


def kalshi_anytime_td():
    """Open '1+ touchdowns' markets with a two-sided quote."""
    out, cursor = [], None
    while True:
        url = f"{API}/markets?series_ticker=KXNFLTD&status=open&limit=200"
        if cursor:
            url += f"&cursor={cursor}"
        page = get(url)
        for m in page.get("markets", []):
            title = m.get("title") or ""
            if not title.endswith("1+ touchdowns"):
                continue
            yes_bid = m.get("yes_bid_dollars")
            no_bid = m.get("no_bid_dollars")
            if yes_bid in (None, "") or no_bid in (None, ""):
                continue
            yes_bid, yes_ask = float(yes_bid), 1 - float(no_bid)
            if yes_bid <= 0 and yes_ask >= 1:
                continue
            out.append({
                "ticker": m["ticker"],
                "player": title.rsplit(":", 1)[0].strip(),
                "event": m.get("event_ticker", ""),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "mid": (yes_bid + yes_ask) / 2,
                "oi": float(m.get("open_interest_fp") or 0),
            })
        cursor = page.get("cursor")
        if not cursor:
            break
    return pd.DataFrame(out)


def norm(name):
    name = re.sub(r"[^a-z ]", "", name.lower())
    return re.sub(r"\s+(jr|sr|ii|iii|iv)$", "", name).strip()


ACTIVE_SINCE = 2025   # a player whose last game predates this is not on a depth chart


def model_probabilities():
    """Latest per-player model probability, using each player's most recent
    week of prior-only features.

    Two corrections matter here. Restricting to recently active players keeps
    retired ones out -- their last snapshot still carries a team, which inflated
    projected team TD shares to ~4.7x reality. Shares are then renormalized so a
    roster sums to one.
    """
    stats = td_model.load_stats()
    games = td_model.load_games()
    df = td_model.build(stats)
    train = df[df.season < 2026].merge(
        games.rename(columns={"team": "recent_team"}),
        on=["season", "week", "recent_team"], how="left")
    coef = td_model.fit_team_tds(train)

    fit = train[train.implied_pts.notna() & (train.usage_prior >= td_model.USAGE_MIN)]
    lam_train = (fit.td_share * (coef[0] + coef[1] * fit.implied_pts)).clip(0.001, 3.0)
    _, b = td_model.platt(lam_train, (fit.tds > 0).astype(int), lam_train)

    latest = df.sort_values(["season", "week"]).groupby("player_id").tail(1)
    latest = latest[(latest.season >= ACTIVE_SINCE)
                    & (latest.usage_prior >= td_model.USAGE_MIN)].copy()
    latest["td_share"] = (latest.td_share
                          / latest.groupby("recent_team").td_share.transform("sum"))
    # (build() already normalizes per team-game; renormalizing here rescales the
    # cross-week snapshot to the current roster)
    latest["key"] = latest.player_display_name.map(norm)
    return latest, coef, b


def upcoming_implied():
    """Per-team implied point total for the next unplayed week."""
    g = pd.read_csv(td_model.GAMES, low_memory=False)
    g = g[(g.season == g.season.max()) & (g.game_type == "REG")
          & g.total_line.notna() & g.home_score.isna()]
    week = int(g.week.min())
    g = g[g.week == week]
    rows = []
    for _, r in g.iterrows():
        rows.append((r.home_team, r.total_line / 2 + r.spread_line / 2))
        rows.append((r.away_team, r.total_line / 2 - r.spread_line / 2))
    return week, pd.DataFrame(rows, columns=["recent_team", "implied_pts"])


def main(min_gap=0.05):
    book = kalshi_anytime_td()
    if book.empty:
        print("no quoted anytime-TD markets right now")
        return
    latest, coef, b = model_probabilities()
    week, implied = upcoming_implied()

    book["key"] = book.player.map(norm)
    merged = book.merge(
        latest[["key", "player_display_name", "position", "recent_team",
                "td_share", "usage_prior", "season", "week"]],
        on="key", how="inner").merge(implied, on="recent_team", how="inner")

    lam = (merged.td_share * (coef[0] + coef[1] * merged.implied_pts)).clip(0.001, 3.0)
    z = b[0] + b[1] * np.log(lam)
    merged["p_model"] = 1 / (1 + np.exp(-z))
    merged["edge"] = merged.p_model - merged.mid

    print(f"week {week}: quoted markets {len(book)}  matched to model {len(merged)}")
    print(f"model mean {merged.p_model.mean():.3f} vs market mean {merged.mid.mean():.3f}")
    bucket = pd.cut(merged.mid, [0, .1, .2, .3, .5, 1.0])
    print("\nmodel vs market by market price:")
    print(merged.groupby(bucket, observed=True).agg(
        n=("edge", "size"), market=("mid", "mean"),
        model=("p_model", "mean"), edge=("edge", "mean")).round(3).to_string())
    print()
    cols = ["player", "recent_team", "position", "implied_pts", "yes_bid", "yes_ask",
            "mid", "p_model", "edge", "oi"]
    big = merged[merged.edge.abs() >= min_gap].sort_values("edge", ascending=False)
    with pd.option_context("display.width", 200, "display.max_rows", 60):
        print(big[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("\nUNVERIFIED: no inactive/depth-chart check applied. Do not bet off this table.")


if __name__ == "__main__":
    main()
