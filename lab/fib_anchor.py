#!/usr/bin/env python3
"""Where should the Fib be drawn from — swing pivots, or the day's own range?

The engine's original Fib anchors the retracement between two confirmed swing pivots, which on a
1-minute chart means many small legs a day. On 2026-08-31 that produced five setups and the 1.5:1
gate refused all five: with the stop at the far end of the leg and the target at the near end the
ratio is capped at 0.618/0.382 = 1.62:1, so on a 7-11 point leg the 0.25 buffer and the
confirmation close are enough to fail it.

Jonathan's rule instead: let the day run 15 minutes, then draw the Fib between the opening bar and
the day's extreme — one big leg per day rather than dozens of small ones. This measures both on
the same history, through the real engine (same gate, cooldown, sizing, exits), Fib setups only
so the ORB neither hides nor helps the result.

    python lab/fib_anchor.py                       # every variant, on the deep history
    python lab/fib_anchor.py --csv data/ES_1min_recent.csv

Each variant runs into its own throwaway journal, so the record in paper_journal.db is untouched.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEEP = BASE / "data" / "SP500_1min_deep.csv"
PY = BASE / ".venv" / "bin" / "python"

# The rule of the day, so the Fib is measured next to the live settings.
COMMON = ["--or-minutes", "3", "--cap-orb-stop", "--exit", "scale_2R", "--runner-pct", "0.25"]

VARIANTS = {
    "pivots": ["--fib-anchor", "pivots"],
    "open15 (live)": ["--fib-anchor", "open15", "--fib-anchor-minutes", "15"],
    "open15 extending": ["--fib-anchor", "open15", "--fib-anchor-minutes", "15",
                         "--fib-anchor-extend"],
    "open30": ["--fib-anchor", "open15", "--fib-anchor-minutes", "30"],
    "open30 extending": ["--fib-anchor", "open15", "--fib-anchor-minutes", "30",
                         "--fib-anchor-extend"],
}


def run(csv: Path, args: list[str], setups: str, min_rr: float | None = None) -> dict:
    """Replay the history once and read the trades back out of the throwaway journal.

    `min_rr` overrides the reward:risk gate through a copy of config.json, so the study can ask
    what the refused setups would have done without editing the live rules.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "journal.db"
        env = dict(os.environ, TRADE_GATE_DB=str(db),
                   TRADE_GATE_REPORTS=str(Path(tmp) / "reports"))
        if min_rr is not None:
            cfg = json.loads((BASE / "config.json").read_text())
            cfg["my_rules"]["min_reward_to_risk"] = min_rr
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(cfg, indent=2))
            env["TRADE_GATE_CONFIG"] = str(path)
        cmd = [str(PY), str(BASE / "paper_engine.py"), "--replay", str(csv), "--speed", "0",
               "--setups", setups, "--reset", "--compare-exits", "", *COMMON, *args]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode:
            sys.exit(f"engine failed: {proc.stderr[-2000:]}")
        setups_seen = proc.stdout.count(" setup — leg")
        rr_refused = proc.stdout.count("Reward:risk is")
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT trade_date, side, entry, stop, target, contracts, exit_price, pnl, setup "
            "FROM trades WHERE setup LIKE '%FIB%' AND pnl IS NOT NULL").fetchall()
        days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM trades").fetchone()[0]
        # The whole day, ORB included: a Fib rule is only worth having if the day is better
        # for it, and a Fib trade can spend the day's trade count or trip a lock.
        all_net, qual = conn.execute(
            "SELECT COALESCE(SUM(day_net), 0), COALESCE(SUM(day_net >= 300), 0) FROM "
            "(SELECT SUM(pnl) AS day_net FROM trades WHERE pnl IS NOT NULL "
            " GROUP BY trade_date)").fetchone()
        conn.close()

    nets = [r[7] for r in rows]
    wins = [n for n in nets if n > 0]
    rs = []
    for _, side, entry, stop, _t, _c, exit_price, _p, _s in rows:
        risk = abs(entry - stop)
        pts = (exit_price - entry) if side == "long" else (entry - exit_price)
        rs.append(pts / risk if risk else 0.0)
    return {
        "signals": setups_seen, "rr_refused": rr_refused,
        "trades": len(rows), "wins": len(wins),
        "net": sum(nets), "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "best": max(nets, default=0.0), "worst": min(nets, default=0.0),
        "days": days, "all_net": all_net, "qualifying": qual,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(DEEP), help="1-minute history to replay")
    ap.add_argument("--setups", default="fib",
                    help="setups to enable; 'fib' isolates the Fib, 'orb,fib' shows the day "
                         "as it would actually trade")
    ap.add_argument("--min-rr", type=float, default=None,
                    help="override the reward:risk gate for the run (live rule is 1.5)")
    ap.add_argument("--fib-target", type=float, default=None,
                    help="Fib target as a multiple of the leg: 1.0 is the leg extreme, "
                         "1.272 the extension past it")
    args = ap.parse_args()
    csv = Path(args.csv)
    if not csv.exists():
        sys.exit(f"no history at {csv} — run lab/deep_history.py first")

    gate = args.min_rr if args.min_rr is not None else 1.5
    target = args.fib_target if args.fib_target is not None else 1.272
    print(f"{csv.name} · setups={args.setups} · min R:R {gate} · target {target}x leg\n")
    head = (f"{'anchor':<18}{'signals':>8}{'R:R no':>8}{'trades':>8}{'wins':>6}"
            f"{'net $':>11}{'avg R':>8}{'day net $':>12}{'qual':>6}")
    print(head)
    print("-" * len(head))
    for name, extra in VARIANTS.items():
        if args.fib_target is not None:
            extra = [*extra, "--fib-target", str(args.fib_target)]
        st = run(csv, extra, args.setups, args.min_rr)
        print(f"{name:<18}{st['signals']:>8}{st['rr_refused']:>8}{st['trades']:>8}{st['wins']:>6}"
              f"{st['net']:>11,.2f}{st['avg_r']:>8.2f}{st['all_net']:>12,.2f}"
              f"{st['qualifying']:>6}")
    print("\nSignals are setups the rule produced; 'R:R no' is how many the reward:risk gate "
          "refused; trades are what the gate and the day's locks let through. 'net $' and "
          "'avg R' are the Fib trades alone; 'day net $' and 'qual' ($300+ days) are every "
          "trade the day took.")


if __name__ == "__main__":
    main()
