"""Summarize what the scanner has logged so far.

python3 report.py            # whole history
python3 report.py --hours 24 # last day only
"""

import argparse
import datetime as dt
import os
import time
import zoneinfo

import scan
import store

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def pt(ts):
    return dt.datetime.fromtimestamp(ts, PACIFIC).strftime("%a %b %d %I:%M %p PT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=None)
    args = ap.parse_args()

    if not os.path.exists(scan.DB_PATH):
        print(f"no database at {scan.DB_PATH} — has the scanner run?")
        return 1
    conn = store.connect(scan.DB_PATH)
    since = int(time.time() - args.hours * 3600) if args.hours else 0

    runs, ok, first, last = conn.execute(
        "SELECT COUNT(*), SUM(error IS NULL), MIN(ts), MAX(ts)"
        " FROM runs WHERE ts >= ?", (since,)).fetchone()
    if not runs:
        print("no runs recorded yet")
        return 0

    print(f"Runs: {runs} ({ok} clean, {runs - ok} errored)")
    print(f"Window: {pt(first)}  ->  {pt(last)}")
    quotes, snaps = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ts) FROM quotes WHERE ts >= ?", (since,)).fetchone()
    print(f"Quotes logged: {quotes} across {snaps} snapshots")

    for kind in ("two_sided", "same_outcome"):
        rows = conn.execute(
            "SELECT ts, game_date, away, home, detail, gross_cents, size, net_dollars"
            " FROM gaps WHERE kind = ? AND ts >= ? ORDER BY net_dollars DESC",
            (kind, since)).fetchall()
        profitable = [r for r in rows if r[7] > 0]
        tradable = [r for r in rows
                    if r[5] >= scan.ALERT_GROSS_CENTS and r[6] >= scan.ALERT_SIZE]
        print(f"\n=== {kind} ===")
        print(f"  observed: {len(rows)}   after fees positive: {len(profitable)}"
              f"   >= {scan.ALERT_GROSS_CENTS}c and >= {scan.ALERT_SIZE} deep: {len(tradable)}")
        if rows:
            pct = 100.0 * len(profitable) / snaps if snaps else 0.0
            print(f"  snapshots containing one: {pct:.2f}% of all snapshots")
        for ts, date, away, home, detail, gross, size, net in rows[:15]:
            print(f"  {pt(ts):24} {away}@{home:4} {detail:44}"
                  f" {gross:5.1f}c  x{int(size):<5} net ${net:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
