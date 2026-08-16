#!/usr/bin/env python3
"""Download the daily history the comparison runs on.

The CSVs are committed so the numbers in COMPARISON.md can be reproduced exactly — Yahoo revises
history, so re-fetching is not guaranteed to give the same file.
"""
import yfinance as yf

SYMBOLS = ("SPY", "QQQ", "TQQQ")


def main() -> None:
    for sym in SYMBOLS:
        d = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False)
        path = f"data/{sym}_daily.csv"
        d.to_csv(path)
        print(f"{sym}: {len(d)} sessions, {d.index[0].date()} → {d.index[-1].date()} -> {path}")


if __name__ == "__main__":
    main()
