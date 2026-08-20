#!/usr/bin/env python3
"""When the first opening-range break stops out, is the second one in the same direction worth taking?

Jonathan's read: the first ORB trade fails a lot. This measures what the re-entry actually did
on every session of 1-minute ES history the free feed still serves.

The first trade is the rule as written: the opening candle (`--candle` minutes) is the base, the
first break of either end is the entry, the stop is the opposite end clamped to the 12-point cap,
the target is `--target` R. If that trade stops out, the re-entry is the same direction, once —
and two triggers are measured side by side:

    close   price closes back through the broken level (the engine's `--orb-reentry` rule)
    touch   price simply trades back through the level again

The engine's 15-minute post-loss cooldown is applied to the re-entry (`--cooldown`), because a
trigger inside the cooldown is a trade the gate would refuse.

Fills come off 1-minute OHLC and a bar covering both the stop and the target is scored as the
stop — pessimistic, the only assumption that cannot flatter the rule.

    python lab/orb_reentry.py --fetch          # refresh data/ES_1min_recent.csv, then study it
    python lab/orb_reentry.py --candle 2       # the 2-minute range the daily record still runs
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
STOP_CAP = 12.0              # points — my_rules.max_stop_points

OPEN_T = dt.time(6, 30)
ENTRY_END = dt.time(9, 30)
FLAT = dt.time(12, 55)

TRIGGERS = ("close", "touch")


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
    all_df = all_df[(all_df.index.time >= dt.time(6, 25)) & (all_df.index.time <= FLAT)]
    all_df[["Open", "High", "Low", "Close", "Volume"]].to_csv(CSV)
    print(f"{len(all_df)} bars, {all_df.index[0].date()} → {all_df.index[-1].date()} -> {CSV}")


def contracts(stop_pts: float) -> int:
    per = stop_pts * POINT_VALUE
    return max(0, min(int(RISK_PER_TRADE // per), MAX_CONTRACTS)) if per else 0


def simulate(bars: pd.DataFrame, side: str, entry: float, stop_pts: float,
             target_r: float) -> dict | None:
    """Walk a trade forward bar by bar: stop, target, or out at the flat time."""
    qty = contracts(stop_pts)
    if not qty or not len(bars):
        return None
    stop = entry - stop_pts if side == "long" else entry + stop_pts
    target = (entry + target_r * stop_pts) if side == "long" else (entry - target_r * stop_pts)
    mfe = 0.0
    for ts, b in bars.iterrows():
        mfe = max(mfe, (b["High"] - entry) if side == "long" else (entry - b["Low"]))
        if (b["Low"] <= stop) if side == "long" else (b["High"] >= stop):
            px, why, t_out = stop, "stop", ts
            break
        if (b["High"] >= target) if side == "long" else (b["Low"] <= target):
            px, why, t_out = target, "target", ts
            break
    else:
        px, why, t_out = bars["Close"].iloc[-1], "flat time", bars.index[-1]
    pts = (px - entry) if side == "long" else (entry - px)
    return {"side": side, "entry": round(entry, 2), "stop_pts": round(stop_pts, 2), "qty": qty,
            "why": why, "t_out": t_out, "pts": round(pts, 2), "r": round(pts / stop_pts, 2),
            "net": round(pts * qty * POINT_VALUE - qty * COMMISSION_RT, 2),
            "mfe_r": round(mfe / stop_pts, 2)}


def run_day(day_bars: pd.DataFrame, candle_min: int, target_r: float,
            cooldown_min: int) -> dict | None:
    """The day's first break, and — if it stopped out — the same-direction re-entry."""
    candle_end = (dt.datetime.combine(dt.date(2000, 1, 1), OPEN_T)
                  + dt.timedelta(minutes=candle_min)).time()
    candle = day_bars[(day_bars.index.time >= OPEN_T) & (day_bars.index.time < candle_end)]
    if len(candle) < candle_min:
        return None
    hi, lo = candle["High"].max(), candle["Low"].min()
    rest = day_bars[(day_bars.index.time >= candle_end) & (day_bars.index.time <= FLAT)]
    row: dict = {"width": round(hi - lo, 2), "broke": False}

    side = t_in = None
    for ts, b in rest[rest.index.time <= ENTRY_END].iterrows():
        if b["High"] >= hi:
            side, entry, t_in = "long", hi, ts
            break
        if b["Low"] <= lo:
            side, entry, t_in = "short", lo, ts
            break
    if side is None:
        return row

    stop_pts = min(hi - lo, STOP_CAP)
    first = simulate(rest[rest.index > t_in], side, entry, stop_pts, target_r)
    if first is None:
        row.update(broke=True, why="no size")
        return row
    row.update(broke=True, side=side, t_in=t_in, **{f"1_{k}": v for k, v in first.items()
                                                    if k not in ("side", "qty")})

    if first["why"] != "stop":
        return row

    # The re-entry: same direction, once, after the cooldown the gate would impose.
    level = hi if side == "long" else lo
    ready = first["t_out"] + dt.timedelta(minutes=cooldown_min)
    after = rest[(rest.index >= ready) & (rest.index.time <= ENTRY_END)]
    for trigger in TRIGGERS:
        hit = None
        for ts, b in after.iterrows():
            if trigger == "close":
                through = b["Close"] > level if side == "long" else b["Close"] < level
                price = b["Close"]
            else:
                through = b["High"] >= level if side == "long" else b["Low"] <= level
                price = level
            if through:
                hit = (ts, price)
                break
        if hit is None:
            row[f"2{trigger}_why"] = "no trigger"
            continue
        ts, price = hit
        second = simulate(rest[rest.index > ts], side, price, stop_pts, target_r)
        if second is None:
            row[f"2{trigger}_why"] = "no bars after the trigger"
            continue
        row[f"2{trigger}_t_in"] = ts
        row.update({f"2{trigger}_{k}": v for k, v in second.items()
                    if k not in ("side", "qty")})
    return row


def report(res: pd.DataFrame, candle_min: int, target_r: float, cooldown_min: int) -> None:
    traded = res[res.get("1_why").notna()] if "1_why" in res else res.iloc[0:0]
    stopped = traded[traded["1_why"] == "stop"]
    print(f"\n===== {candle_min}-minute opening range · target {target_r}R · "
          f"stop capped at {STOP_CAP:g} pts · {cooldown_min}-min cooldown before a re-entry "
          f"=====")
    print(f"{len(res)} sessions · {len(traded)} took the break · "
          f"median range {res['width'].median():.2f} pts")
    if not len(traded):
        return
    print(f"\nFirst trade: stopped out {len(stopped)} ({len(stopped) / len(traded):.0%}), "
          f"hit {target_r}R {(traded['1_why'] == 'target').sum()} "
          f"({(traded['1_why'] == 'target').mean():.0%}), "
          f"out at the flat time {(traded['1_why'] == 'flat time').sum()}")
    print(f"  net ${traded['1_net'].sum():+,.2f} · ${traded['1_net'].mean():+,.2f} per trade "
          f"· {traded['1_r'].mean():+.2f}R average")

    for trigger in TRIGGERS:
        why, net, r = f"2{trigger}_why", f"2{trigger}_net", f"2{trigger}_r"
        if why not in stopped:
            continue
        took = stopped[stopped[why].isin(("stop", "target", "flat time"))]
        label = ("closes back through the level" if trigger == "close"
                 else "trades back through the level")
        print(f"\nRe-entry, same direction, when price {label}:")
        print(f"  triggered on {len(took)} of the {len(stopped)} stop-out days "
              f"({len(took) / len(stopped):.0%})" if len(stopped) else "  no stop-out days")
        if not len(took):
            continue
        wins = (took[why] == "target").sum()
        stops = (took[why] == "stop").sum()
        print(f"  of those {len(took)} re-entries: hit {target_r}R {wins} "
              f"({wins / len(took):.0%}), stopped out {stops} ({stops / len(took):.0%}), "
              f"out at the flat time {(took[why] == 'flat time').sum()}")
        print(f"  net ${took[net].sum():+,.2f} · ${took[net].mean():+,.2f} per re-entry "
              f"· {took[r].mean():+.2f}R average")
        first_net = took["1_net"].sum()
        print(f"  those days: ${first_net:+,.2f} from the first trade alone, "
              f"${first_net + took[net].sum():+,.2f} with the re-entry")
        recovered = (took["1_net"] + took[net] > 0).sum()
        print(f"  {recovered} of {len(took)} finished the day green after the first loss")
        print(f"  whole sample: ${traded['1_net'].sum():+,.2f} first trades only, "
              f"${traded['1_net'].sum() + took[net].sum():+,.2f} with re-entries")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="refresh the CSV first")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--candle", type=int, nargs="+", default=[3, 2],
                    help="opening range lengths to measure, in minutes")
    ap.add_argument("--target", type=float, default=1.5, help="target in R")
    ap.add_argument("--cooldown", type=int, default=15,
                    help="minutes the gate makes you wait after a loss")
    ap.add_argument("--detail", action="store_true", help="print the per-session table")
    args = ap.parse_args()

    if args.fetch:
        fetch()
    df = pd.read_csv(args.csv, index_col=0, parse_dates=True).tz_convert(PT)
    df = df[["Open", "High", "Low", "Close"]].dropna()

    for candle_min in args.candle:
        rows = [{"date": day, **r} for day, bars in df.groupby(df.index.date)
                if (r := run_day(bars, candle_min, args.target, args.cooldown))]
        res = pd.DataFrame(rows)
        report(res, candle_min, args.target, args.cooldown)
        if args.detail:
            cols = ["date", "width", "side", "1_why", "1_r", "1_net",
                    "2close_why", "2close_r", "2close_net",
                    "2touch_why", "2touch_r", "2touch_net"]
            print("\nPer session:")
            print(res.reindex(columns=cols).to_string(index=False))

    print("\nSmall sample: the free feed serves about a month of 1-minute futures history, so "
          "this is a few dozen sessions of one regime with simulated fills. It is a hint about "
          "the rule, not evidence of an edge — the Strategy Tester on years of MES data is.")


if __name__ == "__main__":
    main()
