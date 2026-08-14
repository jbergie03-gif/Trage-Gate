"""Pilot backtest of the 3-minute opening range break on ES, one exit rule at a time.

The point is not the P&L — 19 sessions of free data cannot establish an edge. The point is
that the SAME entry produces very different results depending on the exit, and that "until
momentum died" has to be replaced by whichever mechanical exit survives on real history in
TradingView (see orb.pine).

    .venv/bin/python backtest_orb.py
"""
from __future__ import annotations

import pandas as pd

CSV = "/home/ubuntu/trade_gate/es_1m.csv"
ET = "America/New_York"
POINT_VALUE_MES = 5.0
RISK_PER_TRADE = 150.0    # the gate's cap on a 100K
MIN_STOP_PTS, MAX_STOP_PTS = 2.0, 12.0
OPEN_H, OPEN_M = 9, 30
SESSION_END = (12, 30)    # 11:30 CT, the end of the personal session window
FLAT_BY = (15, 55)        # hard flat, well before the close


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, header=[0, 1], index_col=0, parse_dates=True)
    df.columns = [c[0] for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df[~df.index.duplicated()].sort_index()


def sessions(df: pd.DataFrame):
    for day, d in df.groupby(df.index.date):
        rth = d[(d.index.hour * 60 + d.index.minute >= OPEN_H * 60 + OPEN_M)
                & (d.index.hour * 60 + d.index.minute < FLAT_BY[0] * 60 + FLAT_BY[1])]
        if len(rth) < 60:
            continue
        yield day, rth


def opening_range(rth: pd.DataFrame, minutes: int = 3):
    """The first N-minute candle, built from N one-minute bars starting at the open."""
    first = rth.iloc[:minutes]
    if len(first) < minutes:
        return None
    return float(first["High"].max()), float(first["Low"].min())


def find_entry(rth: pd.DataFrame, hi: float, lo: float, minutes: int = 3):
    """First break of either end after the opening range closes."""
    for ts, bar in rth.iloc[minutes:].iterrows():
        if bar["High"] >= hi:
            return ts, "long", hi
        if bar["Low"] <= lo:
            return ts, "short", lo
    return None, None, None


def walk(rth, entry_ts, side, entry, stop, exit_rule, r_pts):
    """Bar-by-bar to the exit. Pessimistic: if a bar spans stop and target, the stop wins."""
    after = rth[rth.index > entry_ts]
    best = entry
    trailing = stop
    target = entry + 2 * r_pts if side == "long" else entry - 2 * r_pts

    for ts, bar in after.iterrows():
        hit_stop = bar["Low"] <= trailing if side == "long" else bar["High"] >= trailing
        hit_tgt = bar["High"] >= target if side == "long" else bar["Low"] <= target

        if exit_rule in ("fixed_2R", "trail_after_1R") and hit_stop:
            return (trailing - entry if side == "long" else entry - trailing), ts, "stop"
        if exit_rule == "fixed_2R" and hit_tgt:
            return (target - entry if side == "long" else entry - target), ts, "target"
        if exit_rule in ("opposite_end", "session_end") and hit_stop:
            return (trailing - entry if side == "long" else entry - trailing), ts, "stop"

        if exit_rule == "trail_after_1R":
            best = max(best, bar["High"]) if side == "long" else min(best, bar["Low"])
            moved = (best - entry) if side == "long" else (entry - best)
            if moved >= r_pts:   # once 1R up, trail a stop 1R behind the extreme
                trailing = (max(trailing, best - r_pts) if side == "long"
                            else min(trailing, best + r_pts))

        mins = ts.hour * 60 + ts.minute
        if exit_rule == "session_end" and mins >= SESSION_END[0] * 60 + SESSION_END[1]:
            px = float(bar["Close"])
            return (px - entry if side == "long" else entry - px), ts, "time"

    last = float(after["Close"].iloc[-1]) if len(after) else entry
    ts = after.index[-1] if len(after) else entry_ts
    return (last - entry if side == "long" else entry - last), ts, "flat"


def run(df, exit_rule, or_minutes: int = 3):
    rows = []
    skipped = 0
    for day, rth in sessions(df):
        orng = opening_range(rth, or_minutes)
        if not orng:
            continue
        hi, lo = orng
        r_pts = hi - lo
        if not (MIN_STOP_PTS <= r_pts <= MAX_STOP_PTS):
            skipped += 1     # the gate refuses this trade: stop outside 2-12 points
            continue
        entry_ts, side, entry = find_entry(rth, hi, lo, or_minutes)
        if entry_ts is None:
            continue
        stop = lo if side == "long" else hi
        pts, exit_ts, why = walk(rth, entry_ts, side, entry, stop, exit_rule, r_pts)
        contracts = max(1, round(RISK_PER_TRADE / (r_pts * POINT_VALUE_MES)))
        rows.append({
            "date": day, "side": side, "stop_pts": round(r_pts, 2),
            "contracts": contracts, "pts": round(pts, 2),
            "R": round(pts / r_pts, 2), "why": why,
            "net": round(pts * contracts * POINT_VALUE_MES - contracts * 1.24, 2),
        })
    return pd.DataFrame(rows), skipped


def main():
    df = load()
    print(f"ES 1-minute data: {df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d}\n"
          f"Entry is always the first break of the opening range, stop at the opposite end,\n"
          f"sized to ${RISK_PER_TRADE:.0f} risk on MES. Only the range length and exit change.\n")

    for or_min in (1, 2, 3, 5):
        print(f"--- opening range = first {or_min}-minute candle ---")
        print(f"{'exit rule':<18}{'trades':>7}{'skip':>6}{'win%':>7}{'avg R':>8}"
              f"{'total R':>9}{'net $':>10}{'$300 days':>11}")
        for rule in ("opposite_end", "fixed_2R", "trail_after_1R", "session_end"):
            t, skipped = run(df, rule, or_min)
            if t.empty:
                print(f"{rule:<18}{'none':>7}{skipped:>6}")
                continue
            wins = (t["pts"] > 0).sum()
            qual = (t["net"] >= 300).sum()
            print(f"{rule:<18}{len(t):>7}{skipped:>6}{100 * wins / len(t):>6.0f}%"
                  f"{t['R'].mean():>8.2f}{t['R'].sum():>9.1f}{t['net'].sum():>10,.0f}"
                  f"{qual:>11}")
        print()

    print("'skip' is sessions the gate refuses because the range is outside 2-12 points.\n")

    # How wide is that first candle, really? This decides whether the setup and the
    # 2-12 point stop rule can coexist at all.
    print("Opening range width on ES, and whether a 2-12 point stop can live with it:")
    for or_min in (1, 2, 3, 5):
        widths = [orng[0] - orng[1]
                  for _, rth in sessions(df)
                  if (orng := opening_range(rth, or_min))]
        w = pd.Series(widths)
        ok = ((w >= MIN_STOP_PTS) & (w <= MAX_STOP_PTS)).mean()
        print(f"  {or_min}-min: median {w.median():>5.1f} pts · min {w.min():>4.1f} · "
              f"max {w.max():>5.1f} · {100 * ok:>3.0f}% of sessions tradable under the rule")

    print("\nRead this as a shape, not a result. Nineteen sessions is far too small a sample")
    print("to establish an edge, and it covers one market regime. Run orb.pine in TradingView")
    print("over several years for numbers worth acting on.")

    detail, _ = run(df, "fixed_2R", 2)
    print("\nEvery trade — 2-minute range, fixed 2R:")
    print(detail.to_string(index=False))


if __name__ == "__main__":
    main()
