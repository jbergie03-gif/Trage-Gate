"""Replay real trade history through the gate.

Feed it a CSV of your own fills (Tradovate -> Reports, the Apex dashboard trade log, or
TradingView's Strategy Tester "List of Trades") and it answers one question: with the same
trades in the same order, where would the rules have stopped you, and would the account
have survived?

Two passes over the same data:
  * WHAT HAPPENED   — every trade, as taken, against the EOD threshold.
  * WITH THE GATE   — trades after a daily lock are dropped, because they never happen.

    .venv/bin/python replay.py trades.csv [--account 100K]

Column names vary by platform; anything reasonable is detected. The minimum needed is a
timestamp and a per-trade P&L. If sizes and prices are present the risk rules are checked
too, otherwise only the daily rules are.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import rules

TS_KEYS = ["closed_at", "close time", "exit time", "timestamp", "date/time", "date",
           "boughttimestamp", "soldtimestamp", "time", "fill time", "tradedate"]
PNL_KEYS = ["pnl", "p/l", "profit", "net p&l", "netpnl", "realized p&l", "pl",
            "profit/loss", "net profit", "gross p&l"]
QTY_KEYS = ["qty", "quantity", "contracts", "size", "filledqty", "position size"]
SYM_KEYS = ["symbol", "contract", "instrument", "product"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9&/ ]", "", s.strip().lower())


def pick(header: list[str], candidates: list[str]) -> str | None:
    cols = {norm(h): h for h in header}
    for c in candidates:
        if c in cols:
            return cols[c]
    for c in candidates:                      # substring fallback
        for n, orig in cols.items():
            if c in n:
                return orig
    return None


def money(v: str) -> float | None:
    if v is None:
        return None
    v = v.strip().replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    if v in ("", "-", "--"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_ts(v: str) -> datetime | None:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d",
                "%m/%d/%y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(v[:len(datetime.now().strftime(fmt)) + 4], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v.replace("Z", "").split("+")[0])
    except ValueError:
        return None


def _tradingview(rows, type_col, ts_col, pnl_col, qty_col, sym_col) -> list[dict]:
    """TradingView's List of Trades: one row per leg, entry and exit each carrying the
    same P&L. Two collapses are needed or the gate sees four trades where you took one:
    drop the entry rows, then merge the legs of a scaled trade (core + runner share an
    entry) back into the single decision they were.
    """
    tnum = pick(list(rows[0].keys()), ["trade number", "trade #"])
    entries: dict[str, datetime | None] = {}
    for r in rows:
        if (r.get(type_col) or "").lower().startswith("entry") and tnum:
            entries[r[tnum]] = parse_ts(r.get(ts_col, "")) if ts_col else None

    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        if not (r.get(type_col) or "").lower().startswith("exit"):
            continue
        pnl = money(r.get(pnl_col))
        if pnl is None:
            continue
        opened = entries.get(r.get(tnum, ""), None) if tnum else None
        ts = opened or (parse_ts(r.get(ts_col, "")) if ts_col else None)
        key = (ts, (r.get(sym_col) or "").strip() if sym_col else "")
        if key not in merged:
            merged[key] = {"ts": ts, "pnl": 0.0, "qty": 0.0, "symbol": key[1], "legs": 0}
            order.append(key)
        m = merged[key]
        m["pnl"] += pnl
        m["qty"] += (money(r.get(qty_col)) or 0.0) if qty_col else 0.0
        m["legs"] += 1

    out = [merged[k] for k in order]
    scaled = sum(1 for t in out if t["legs"] > 1)
    print(f"TradingView export: {len(out)} trades "
          f"({scaled} of them scaled out in more than one piece, merged into one trade each)")
    for t in out:
        t.pop("legs")
        t["pnl"] = round(t["pnl"], 2)
    return out


def load(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(fh, dialect=dialect))
    if not rows:
        sys.exit(f"{path} has no rows.")

    header = list(rows[0].keys())
    ts_col = pick(header, TS_KEYS)
    pnl_col = pick(header, PNL_KEYS)
    qty_col = pick(header, QTY_KEYS)
    sym_col = pick(header, SYM_KEYS)
    if not pnl_col:
        sys.exit(f"Could not find a P&L column in: {header}\n"
                 "Rename the column to 'pnl' and try again.")
    print(f"Columns detected — time: {ts_col or 'MISSING'}  P&L: {pnl_col}  "
          f"qty: {qty_col or 'n/a'}  symbol: {sym_col or 'n/a'}")

    type_col = pick(header, ["type"])
    if type_col and any((r.get(type_col) or "").lower().startswith(("entry", "exit"))
                        for r in rows):
        return _tradingview(rows, type_col, ts_col, pnl_col, qty_col, sym_col)

    out = []
    for r in rows:
        pnl = money(r.get(pnl_col))
        if pnl is None:
            continue
        ts = parse_ts(r.get(ts_col, "")) if ts_col else None
        out.append({
            "ts": ts,
            "pnl": pnl,
            "qty": money(r.get(qty_col)) if qty_col else None,
            "symbol": (r.get(sym_col) or "").strip() if sym_col else "",
        })
    if not out:
        sys.exit("No rows had a readable P&L value.")
    return out


def trade_day(ts: datetime | None, n: int) -> str:
    """Apex's day rolls at 18:00 ET, so an evening trade belongs to the next day."""
    if ts is None:
        return f"row-group-{n // 5}"          # no timestamps: bucket 5 trades per 'day'
    d = ts + timedelta(hours=6)               # 18:00 ET boundary
    return d.strftime("%Y-%m-%d")


def replay(trades: list[dict], lim, enforce: bool):
    """Walk the trades in order. Returns a per-day story and the account's fate."""
    days = defaultdict(list)
    for i, t in enumerate(trades):
        days[trade_day(t["ts"], i)].append(t)
    max_trades = rules.load_config()["my_rules"]["max_trades_per_day"]

    pnl = 0.0
    eod_high = 0.0
    taken = skipped = 0
    day_rows = []
    failed_on = None

    for day in sorted(days):
        threshold = eod_high - lim.eod_drawdown
        day_pnl = 0.0
        consec = 0
        count = 0
        locked = None

        for t in days[day]:
            if enforce and locked:
                skipped += 1
                continue
            day_pnl += t["pnl"]
            taken += 1
            count += 1
            consec = consec + 1 if t["pnl"] < 0 else 0

            if pnl + day_pnl <= threshold and failed_on is None:
                failed_on = day
            if enforce:
                if day_pnl >= lim.daily_target:
                    locked = f"target +{lim.daily_target:,.0f} reached"
                elif day_pnl <= -lim.max_daily_loss:
                    locked = f"daily stop -{lim.max_daily_loss:,.0f} hit"
                elif consec >= 2:
                    locked = "two losses in a row"
                elif count >= max_trades:
                    locked = f"{max_trades} trades taken"

        pnl += day_pnl
        eod_high = max(eod_high, pnl)
        day_rows.append({
            "day": day,
            "trades": f"{count}/{len(days[day])}" if enforce else str(len(days[day])),
            "pnl": round(day_pnl, 2),
            "cum": round(pnl, 2), "threshold": round(threshold, 2),
            "locked": locked or "",
            "qualifying": day_pnl >= lim.min_daily_profit,
        })
        if failed_on == day and not enforce:
            break
        if failed_on == day and enforce:
            break

    return {
        "days": day_rows,
        "final": round(pnl, 2),
        "peak": round(eod_high, 2),
        "taken": taken,
        "skipped": skipped,
        "failed_on": failed_on,
        "qualifying_days": sum(1 for d in day_rows if d["qualifying"]),
    }


def report(name, res, lim):
    print(f"\n=== {name} ===")
    print(f"{'day':<14}{'taken':>7}{'day P&L':>11}{'cumulative':>12}"
          f"{'threshold':>11}   note")
    for d in res["days"][-40:]:
        note = d["locked"]
        if d["qualifying"]:
            note = (note + "  " if note else "") + "qualifying day"
        print(f"{d['day']:<14}{d['trades']:>7}{d['pnl']:>11,.2f}{d['cum']:>12,.2f}"  
              f"{d['threshold']:>11,.2f}   {note}")
    print(f"trades taken {res['taken']}"
          + (f", skipped by the rules {res['skipped']}" if res["skipped"] else ""))
    print(f"final {res['final']:,.2f} · peak {res['peak']:,.2f} · "
          f"qualifying days {res['qualifying_days']}/5")
    if res["failed_on"]:
        print(f"ACCOUNT LOST on {res['failed_on']} — cumulative P&L touched the EOD threshold")
    elif res["final"] >= lim.profit_to_first_request and res["qualifying_days"] >= 5:
        print("Account survived AND cleared the profit and qualifying-day requirements.")
    else:
        print("Account survived. Payout requirements not yet met.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--account", default=None, help="25K, 50K, 100K or 150K")
    args = ap.parse_args()

    cfg = rules.load_config()
    if args.account:
        cfg["active_account"] = args.account
    lim = rules.limits(cfg)
    trades = load(args.csv)

    print(f"\n{len(trades)} trades · {lim.account} EOD · drawdown {lim.eod_drawdown:,.0f} · "
          f"target {lim.daily_target:,.0f}/day · stop {lim.max_daily_loss:,.0f}/day · "
          f"qualifying day {lim.min_daily_profit:,.0f}")

    report("WHAT HAPPENED (no rules)", replay(trades, lim, enforce=False), lim)
    report("WITH THE GATE", replay(trades, lim, enforce=True), lim)

    print("\nThe second block drops every trade that came after a daily lock, because under"
          "\nthe rules those trades never happen. If the difference between the two blocks is"
          "\nlarge, the accounts were lost to what you did after the day was already decided."
          "\nIf both blocks lose, the entries themselves need work before any account is safe.")


if __name__ == "__main__":
    main()
