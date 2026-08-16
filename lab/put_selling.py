#!/usr/bin/env python3
"""What selling 10-delta puts every week actually pays, and what the 10% costs.

The claim under test: 10-day, 10-delta short puts on an uptrending name, cash-secured, roughly
90% win rate, "worst case I own the shares at a discount". The win rate is true by construction —
10 delta means about a 90% chance of expiring worthless. The only question worth asking is what
happens in the other 10%, and no track record that started in a bull market can answer it.

There is no free historical options data, so prices come from Black-Scholes with VIX as the
volatility input and a skew multiplier, because out-of-the-money index puts trade at a higher
implied vol than at-the-money. That makes this a model, not a fill record: it gets the shape and
the order of magnitude right, and every number should be read with the skew sensitivity table at
the bottom in mind.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

ANNUAL_DAYS = 252
CONTRACT = 100                  # shares per option contract
COMMISSION = 0.65               # per contract, each way
SLIP_PER_SHARE = 0.02           # half the bid/ask on a liquid weekly, per share


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def nppf(p: float) -> float:
    """Inverse standard normal CDF, Acklam's rational approximation with one Halley step.

    Written out rather than pulling in scipy: the repo currently needs only numpy and pandas,
    and the daily automation runs in the same environment.
    """
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    e = ncdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def load_prices(symbol: str) -> pd.DataFrame:
    d = pd.read_csv(f"data/{symbol}_daily.csv", index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York") \
                .tz_localize(None).normalize()
    d = d[["Open", "High", "Low", "Close", "Adj Close"]].dropna()
    ratio = d["Adj Close"] / d["Close"]
    for col in ("Open", "High", "Low", "Close"):
        d[col] = d[col] * ratio
    return d


def load_vix() -> pd.Series:
    d = pd.read_csv("data/VIX_daily.csv", index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York") \
                .tz_localize(None).normalize()
    return d["Close"] / 100.0


def put_price(s: float, k: float, t: float, vol: float, r: float = 0.03) -> float:
    """Black-Scholes put. t in years."""
    if t <= 0 or vol <= 0:
        return max(k - s, 0.0)
    d1 = (math.log(s / k) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    return k * math.exp(-r * t) * ncdf(-d2) - s * ncdf(-d1)


def strike_for_delta(s: float, target_delta: float, t: float, vol: float,
                     r: float = 0.03) -> float:
    """The strike whose put delta is -target_delta.

    Put delta = -N(-d1), so solving N(-d1) = target_delta gives d1 directly and the strike
    follows in closed form. No search needed.
    """
    d1 = -nppf(target_delta)
    return s * math.exp(-d1 * vol * math.sqrt(t) + (r + vol * vol / 2) * t)


@dataclass
class Trade:
    opened: pd.Timestamp
    expires: pd.Timestamp
    spot: float
    strike: float
    iv: float
    premium: float          # per share, net of slippage
    settle: float
    pnl: float              # dollars per contract
    collateral: float
    assigned: bool


def sell_puts(px: pd.DataFrame, vix: pd.Series, delta: float = 0.10, dte: int = 10,
              skew: float = 1.3, roll_days: int = 7) -> list[Trade]:
    """Sell one cash-secured put every roll_days trading days, hold to expiry.

    Held to expiry rather than closed early at a profit target. Closing at "+100%" the way the
    marketing describes improves the win rate and does nothing for the tail, which is the only
    part in question here.
    """
    trades: list[Trade] = []
    iv_all = (vix.reindex(px.index).ffill() * skew).dropna()
    i = 0
    idx = px.index
    while i < len(idx):
        ts = idx[i]
        if ts not in iv_all.index:
            i += 1
            continue
        expiry_ts = ts + pd.Timedelta(days=dte)
        later = idx[idx >= expiry_ts]
        if len(later) == 0:
            break
        exp = later[0]
        s0, iv = px.Close.loc[ts], float(iv_all.loc[ts])
        t = dte / 365.0
        k = strike_for_delta(s0, delta, t, iv)
        prem = put_price(s0, k, t, iv) - SLIP_PER_SHARE
        settle = px.Close.loc[exp]
        intrinsic = max(k - settle, 0.0)
        pnl = (prem - intrinsic) * CONTRACT - COMMISSION * (2 if intrinsic > 0 else 1)
        trades.append(Trade(ts, exp, s0, k, iv, prem, settle, pnl, k * CONTRACT,
                            intrinsic > 0))
        i += roll_days
    return trades


def report(trades: list[Trade], label: str) -> dict:
    """Score the strategy on the money it ties up, not on the premium it collects.

    A cash-secured put only looks like a high yield if you forget the collateral, which is the
    number the marketing always leaves out. 'Weeks of premium lost' is the one that matters:
    how long the 90% has to keep working to pay back one visit from the 10%.
    """
    pnl = np.array([t.pnl for t in trades])
    coll = np.array([t.collateral for t in trades])
    prem = np.array([t.premium * CONTRACT for t in trades])
    years = (trades[-1].expires - trades[0].opened).days / 365.25
    per_year = len(trades) / years
    # Return on the collateral that had to sit there, compounded.
    yearly_pnl = pnl.sum() / years
    return {
        "underlying": label,
        "trades": len(trades),
        "win %": round(100 * (pnl > 0).mean(), 1),
        "avg premium $": round(float(prem.mean()), 2),
        "avg collateral $": round(float(coll.mean()), 0),
        "premium % of collateral": round(float(np.mean(prem / coll) * 100), 3),
        "return on collateral %/yr": round(float(yearly_pnl / coll.mean() * 100), 2),
        "worst trade $": round(float(pnl.min()), 2),
        "worst % of collateral": round(float((pnl / coll).min() * 100), 1),
        "worst trade = N weeks premium": round(float(-pnl.min() / prem.mean()), 1),
        "trades/yr": round(per_year, 1),
    }


def worst_episodes(trades: list[Trade], n: int = 8) -> pd.DataFrame:
    rows = [{"opened": t.opened.date(), "spot": round(t.spot, 2),
             "strike": round(t.strike, 2), "settle": round(t.settle, 2),
             "IV %": round(t.iv * 100, 1), "premium $": round(t.premium * CONTRACT, 2),
             "P&L $": round(t.pnl, 2),
             "% of collateral": round(t.pnl / t.collateral * 100, 1)}
            for t in sorted(trades, key=lambda x: x.pnl)[:n]]
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", type=float, default=2500.0)
    ap.add_argument("--delta", type=float, default=0.10)
    ap.add_argument("--dte", type=int, default=10)
    ap.add_argument("--symbols", default="SPY")
    args = ap.parse_args()

    vix = load_vix()
    print(f"Pricing model: Black-Scholes, VIX as the vol input, skew multiplier applied to "
          f"reflect that out-of-the-money puts trade richer than at-the-money.")
    print(f"Costs: ${COMMISSION}/contract each way, ${SLIP_PER_SHARE}/share of spread.")
    print(f"Account: ${args.account:,.0f}. Cash-secured means collateral = strike x 100.\n")

    for skew in (1.0, 1.3, 1.6):
        rows = []
        for sym in args.symbols.split(","):
            px = load_prices(sym)
            trades = sell_puts(px, vix, delta=args.delta, dte=args.dte, skew=skew)
            if trades:
                rows.append(report(trades, sym))
        print(f"=== {args.delta:.2f} delta, {args.dte} DTE, skew x{skew} ===")
        print(pd.DataFrame(rows).to_string(index=False))
        print()

    px = load_prices(args.symbols.split(",")[0])
    trades = sell_puts(px, vix, delta=args.delta, dte=args.dte, skew=1.3)
    by_year = pd.Series({t.opened.year: 0 for t in trades}, dtype=float)
    for t in trades:
        by_year[t.opened.year] += t.pnl
    losers = by_year[by_year < 0]
    print("=== Losing years, one contract, skew x1.3 (collateral ~"
          f"${np.mean([t.collateral for t in trades]):,.0f}) ===")
    print(", ".join(f"{y} ${v:,.0f}" for y, v in losers.items()))
    print(f"{len(losers)} losing years out of {len(by_year)}; "
          f"worst {losers.min():,.0f}, median year +${by_year.median():,.0f}\n")

    print(f"A ${args.account:,.0f} account cannot secure any of these: SPY's average strike "
          f"needs ${np.mean([t.collateral for t in trades]):,.0f} of cash per contract. "
          f"See lab/put_screen.py for what it can secure.\n")

    print("=== The 10%: worst single trades, one contract, skew x1.3 ===")
    print(worst_episodes(trades).to_string(index=False))

    # Buy-and-hold over the same window, for the comparison the marketing never shows.
    first, last = trades[0].opened, trades[-1].expires
    held = px.Close.loc[first:last]
    years = (last - first).days / 365.25
    print(f"\nSPY buy and hold over the same window: "
          f"{100 * ((held.iloc[-1] / held.iloc[0]) ** (1 / years) - 1):.2f}% CAGR, "
          f"max drawdown "
          f"{100 * (held / held.cummax() - 1).min():.1f}%")


if __name__ == "__main__":
    main()
