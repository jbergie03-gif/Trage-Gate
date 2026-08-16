#!/usr/bin/env python3
"""Which underlyings a $2,500 cash-secured put account can actually reach, and what they pay.

The constraint is arithmetic: securing one put means holding strike x 100 in cash, so a $2,500
account needs a strike under $25 — one position at a time, no diversification. This prices a
10-delta, 10-day put on every candidate under that ceiling using each name's own realised
volatility, and puts the weekly income next to the worst 10-day fall in its history.

The point is not to find the best premium. Premium rises with volatility, so the best-paying name
is by definition the one where 'worst case I own the shares' hurts most, and that trade-off is
what the table is for.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import yfinance as yf

from put_selling import CONTRACT, COMMISSION, SLIP_PER_SHARE, put_price, strike_for_delta

# Liquid, optionable, and plausibly under $25 a share. Mixed on purpose: index and sector ETFs,
# large caps that trade cheap, and a few high-volatility names to show what the premium costs.
CANDIDATES = ("F", "INTC", "PFE", "T", "KO", "CSCO", "BAC", "WBD", "SOFI", "AAL", "RIVN",
              "NIO", "MARA", "PLUG", "SIRI", "HBAN", "KVUE", "VALE", "GRAB", "LCID",
              "XLF", "XLE", "SLV", "GDX", "EEM", "IWM", "SPY", "QQQ", "TQQQ")


def stats(sym: str, lookback: int = 504) -> dict | None:
    d = yf.Ticker(sym).history(period="5y", interval="1d", auto_adjust=True)
    if len(d) < 260:
        return None
    close = d["Close"].dropna()
    ret = close.pct_change().dropna()
    vol = float(ret.tail(lookback).std() * np.sqrt(252))
    spot = float(close.iloc[-1])
    # Worst 10-trading-day fall in five years: the assignment case, measured rather than assumed.
    worst_10d = float((close / close.shift(10) - 1).min())
    return {"symbol": sym, "spot": spot, "realised vol %": vol * 100, "worst 10d %": worst_10d * 100}


def price_trade(spot: float, vol: float, delta: float, dte: int, skew: float) -> dict:
    t = dte / 365.0
    iv = vol * skew
    k = strike_for_delta(spot, delta, t, iv)
    prem = put_price(spot, k, t, iv) - SLIP_PER_SHARE
    return {"strike": k, "iv %": iv * 100, "premium $": prem * CONTRACT - COMMISSION,
            "collateral $": k * CONTRACT}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", type=float, default=2500.0)
    ap.add_argument("--delta", type=float, default=0.10)
    ap.add_argument("--dte", type=int, default=10)
    ap.add_argument("--skew", type=float, default=1.3)
    args = ap.parse_args()

    rows = []
    for sym in CANDIDATES:
        s = stats(sym)
        if s is None:
            print(f"{sym}: not enough history, skipped")
            continue
        p = price_trade(s["spot"], s["realised vol %"] / 100, args.delta, args.dte, args.skew)
        contracts = int(args.account // p["collateral $"])
        # If the 10-day fall that already happened repeated while the put was open.
        assigned_at = p["strike"]
        crash_px = s["spot"] * (1 + s["worst 10d %"] / 100)
        loss = max(assigned_at - crash_px, 0.0) * CONTRACT - p["premium $"]
        rows.append({
            "symbol": sym,
            "spot $": round(s["spot"], 2),
            "vol %": round(s["realised vol %"], 1),
            "10d 10Δ strike": round(p["strike"], 2),
            "collateral $": round(p["collateral $"], 0),
            "contracts on account": contracts,
            "premium/trade $": round(p["premium $"], 2),
            "premium % of collateral": round(p["premium $"] / p["collateral $"] * 100, 2),
            "income $/yr (36 rolls)": round(p["premium $"] * contracts * 36, 0),
            "worst 10d fall %": round(s["worst 10d %"], 1),
            "loss if repeated $": round(-loss * contracts, 0),
        })

    df = pd.DataFrame(rows)
    afford = df[df["contracts on account"] >= 1].sort_values("premium % of collateral",
                                                             ascending=False)
    cannot = df[df["contracts on account"] < 1].sort_values("collateral $")

    print(f"\n=== Reachable with ${args.account:,.0f}: {args.delta:.2f} delta, {args.dte} DTE, "
          f"skew x{args.skew} ===")
    print(afford.to_string(index=False) if len(afford) else "none")
    print(f"\n=== Out of reach (collateral above the account) ===")
    print(cannot[["symbol", "spot $", "collateral $"]].to_string(index=False))

    if len(afford):
        best = afford.iloc[0]
        print(f"\nBest premium yield reachable: {best['symbol']} at "
              f"{best['premium % of collateral']:.2f}% of collateral per trade, "
              f"${best['income $/yr (36 rolls)']:,.0f}/yr if nothing ever goes wrong — against "
              f"${-best['loss if repeated $']:,.0f} if its own worst 10-day fall "
              f"({best['worst 10d fall %']:.0f}%) happens once while the put is open.")


if __name__ == "__main__":
    main()
