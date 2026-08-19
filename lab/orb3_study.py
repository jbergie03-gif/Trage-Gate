#!/usr/bin/env python3
"""Does the opening 3-minute candle's width tell you anything about the break?

Jonathan's read was that a wide opening candle rarely follows through, so the ORB should be
skipped on those days. This measures it on every session of 1-minute ES history the free feed
still serves (~a month), splitting sessions at the 12-point stop cap.

The rule measured here is his: the 06:30-06:32 PT candle is the base, the first break of either
end is the entry, the stop is the opposite end (optionally clamped to the 12-point cap), the
target is 1.5R. Fills come off 1-minute OHLC and a bar covering both the stop and the target is
scored as the stop — pessimistic, because it is the only assumption that cannot flatter the rule.

    python lab/orb3_study.py --fetch      # refresh data/ES_1min_recent.csv, then study it
    python lab/orb3_study.py              # study the committed CSV
"""
import argparse
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
CSV = BASE / "data" / "ES_1min_recent.csv"
PT = ZoneInfo("America/Los_Angeles")

POINT_VALUE = 5.0            # MES
COMMISSION_RT = 1.24
RISK_PER_TRADE = 150.0
MAX_CONTRACTS = 8
TARGET_R = 1.5
STOP_CAP = 12.0              # points — my_rules.max_stop_points

OPEN_T = dt.time(6, 30)
CANDLE_END = dt.time(6, 33)      # exclusive: the 06:30, 06:31 and 06:32 bars
ENTRY_END = dt.time(9, 30)
FLAT = dt.time(12, 55)


def fetch() -> None:
    """Pull the last month of 1-minute bars in 7-day chunks — the feed's limit."""
    import yfinance as yf
    frames = []
    end = dt.date.today() + dt.timedelta(days=1)
    cur = end - dt.timedelta(days=30)
    while cur < end:
        stop = min(cur + dt.timedelta(days=7), end)
        df = yf.download("ES=F", start=cur.isoformat(), end=stop.isoformat(),
                         interval="1m", progress=False, auto_adjust=False)
        if df is not None and len(df):
            if df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)
            frames.append(df)
        cur = stop
    all_df = pd.concat(frames).sort_index()
    all_df = all_df[~all_df.index.duplicated(keep="first")].tz_convert(PT)
    # Only the session window is of any use here, and it keeps the CSV small.
    all_df = all_df[(all_df.index.time >= dt.time(6, 25)) & (all_df.index.time <= FLAT)]
    all_df[["Open", "High", "Low", "Close", "Volume"]].to_csv(CSV)
    print(f"{len(all_df)} bars, {all_df.index[0].date()} → {all_df.index[-1].date()} -> {CSV}")


def contracts(stop_pts: float) -> int:
    per = stop_pts * POINT_VALUE
    return max(0, min(int(RISK_PER_TRADE // per), MAX_CONTRACTS)) if per else 0


def run_day(day_bars: pd.DataFrame, cap_stop: bool) -> dict | None:
    candle = day_bars[(day_bars.index.time >= OPEN_T) & (day_bars.index.time < CANDLE_END)]
    if len(candle) < 3:
        return None
    hi, lo = candle["High"].max(), candle["Low"].min()
    rest = day_bars[(day_bars.index.time >= CANDLE_END) & (day_bars.index.time <= FLAT)]
    out = {"width": round(hi - lo, 2), "broke": False}

    side = None
    for ts, b in rest[rest.index.time <= ENTRY_END].iterrows():
        if b["High"] >= hi:
            side, entry, t_in = "long", hi, ts
            break
        if b["Low"] <= lo:
            side, entry, t_in = "short", lo, ts
            break
    if side is None:
        return out

    stop_pts = min(hi - lo, STOP_CAP) if cap_stop else hi - lo
    stop = entry - stop_pts if side == "long" else entry + stop_pts
    target = entry + TARGET_R * stop_pts if side == "long" else entry - TARGET_R * stop_pts
    qty = contracts(stop_pts)
    out.update(broke=True, side=side, t_in=t_in.strftime("%H:%M"), entry=entry,
               stop_pts=round(stop_pts, 2), qty=qty)
    if qty == 0:
        out["why"] = "no size"
        return out

    after = rest[rest.index > t_in]
    if not len(after):
        out["why"] = "no bars after entry"
        return out
    mfe = 0.0
    for ts, b in after.iterrows():
        mfe = max(mfe, (b["High"] - entry) if side == "long" else (entry - b["Low"]))
        if (b["Low"] <= stop) if side == "long" else (b["High"] >= stop):
            px, why, t_out = stop, "stop", ts
            break
        if (b["High"] >= target) if side == "long" else (b["Low"] <= target):
            px, why, t_out = target, "target", ts
            break
    else:
        px, why, t_out = after["Close"].iloc[-1], "flat time", after.index[-1]

    pts = (px - entry) if side == "long" else (entry - px)
    out.update(why=why, t_out=t_out.strftime("%H:%M"), pts=round(pts, 2),
               r=round(pts / stop_pts, 2),
               net=round(pts * qty * POINT_VALUE - qty * COMMISSION_RT, 2),
               mfe_r=round(mfe / stop_pts, 2))
    return out


def study(df: pd.DataFrame, cap_stop: bool) -> pd.DataFrame:
    rows = [{"date": day, **r} for day, bars in df.groupby(df.index.date)
            if (r := run_day(bars, cap_stop))]
    res = pd.DataFrame(rows)
    label = f"stop capped at {STOP_CAP:g} pts" if cap_stop else "stop = the full candle"
    print(f"\n===== 3-minute opening candle break · {label} · target {TARGET_R}R =====")
    print(f"{len(res)} sessions · median candle {res['width'].median():.2f} pts")

    for name, sub in (("candle > 12 pts", res[res.width > STOP_CAP]),
                      ("candle <= 12 pts", res[res.width <= STOP_CAP])):
        if not len(sub):
            continue
        broke = sub[sub.broke]
        traded = broke[broke["net"].notna()] if "net" in broke else broke.iloc[0:0]
        print(f"\n{name}: {len(sub)} sessions ({len(sub) / len(res):.0%})")
        print(f"  broke the candle inside the entry window: {len(broke)}/{len(sub)} "
              f"({len(broke) / len(sub):.0%})")
        if not len(traded):
            continue
        stops = (traded.why == "stop").sum()
        wins = (traded.why == "target").sum()
        print(f"  of {len(traded)} trades: stopped out {stops} ({stops / len(traded):.0%}), "
              f"hit {TARGET_R}R {wins} ({wins / len(traded):.0%}), "
              f"out at flat time {(traded.why == 'flat time').sum()}")
        print(f"  net ${traded.net.sum():+,.2f} total · ${traded.net.mean():+,.2f} per trade "
              f"· {traded.r.mean():+.2f}R average")
        print(f"  best excursion before the exit: median {traded.mfe_r.median():.2f}R · "
              f"{(traded.mfe_r >= 1).mean():.0%} of trades ever reached 1R")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="refresh the CSV first")
    ap.add_argument("--csv", default=str(CSV))
    args = ap.parse_args()
    if args.fetch:
        fetch()
    df = pd.read_csv(args.csv, index_col=0, parse_dates=True).tz_convert(PT)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    capped = study(df, cap_stop=True)
    study(df, cap_stop=False)
    cols = ["date", "width", "broke", "side", "t_in", "stop_pts", "qty", "why", "t_out",
            "pts", "r", "net", "mfe_r"]
    print("\nPer session, stop capped at 12 pts:")
    print(capped.reindex(columns=cols).to_string(index=False))


if __name__ == "__main__":
    main()
