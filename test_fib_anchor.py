"""Checks on where the Fib gets drawn from.

The engine can anchor the retracement two ways: between confirmed swing pivots (the original
rule) or between the opening bar and the day's extreme once the day has run a while (the rule
Jonathan reads off his chart). The geometry is the whole trade — leg, .618, stop and target all
come out of those two points — so it is driven here with hand-built bars whose shape is the thing
being asserted. The journal is a throwaway file; nothing touches paper_journal.db.

    python test_fib_anchor.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TMP = Path(tempfile.mkdtemp(prefix="fib-anchor-tests-"))
os.environ["TRADE_GATE_DB"] = str(TMP / "journal.db")
os.environ["TRADE_GATE_REPORTS"] = str(TMP / "reports")

import paper_engine as pe  # noqa: E402
import rules  # noqa: E402

CT = ZoneInfo("America/Chicago")
OPEN = datetime(2026, 1, 5, 8, 30, tzinfo=CT)
fails: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


def check_close(name: str, got, want: float, tol: float = 0.01) -> None:
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        fails.append(name)


def engine(**kw) -> pe.PaperEngine:
    eng = pe.PaperEngine(rules.load_config(), or_minutes=3, exit_rule="scale_2R", verbose=False,
                         setups=("fib",), fib_anchor="open15", **kw)
    eng.session = pe.Session(date="2026-01-05")
    return eng


def bar(minute: int, high: float, low: float, close: float | None = None) -> pe.Bar:
    ts = OPEN + timedelta(minutes=minute)
    return pe.Bar(ts=ts, open=(high + low) / 2, high=high, low=low,
                  close=close if close is not None else (high + low) / 2)


def feed(eng: pe.PaperEngine, bars: list[pe.Bar]) -> None:
    """Bars into the anchor only — entries are the rest of the engine's business."""
    for b in bars:
        eng.session.bars_seen.append(b)
        eng._track_day_range(b)
        eng._anchor_open15(b)


print("--- the open15 anchor waits for the day to run before it draws anything ---")
eng = engine(fib_anchor_minutes=15)
feed(eng, [bar(m, 5010 + m, 5000 + m) for m in range(10)])
check("no leg before the anchor time", eng.session.fib_anchored, False)
check("and no direction to trade", eng.session.leg_dir, 0)

print("\n--- a high made after the low is an up leg, bought on the pullback ---")
eng = engine(fib_anchor_minutes=15)
# Low at minute 2, high at minute 12: the move is up, so the retracement is bought.
bars = [bar(0, 5005, 5000), bar(2, 5004, 4990), bar(12, 5020, 5010)]
bars += [bar(m, 5015, 5011) for m in (15, 16)]
feed(eng, bars)
s = eng.session
check("leg is anchored once the day has run 15 minutes", s.fib_anchored, True)
check("direction is up — the high printed last", s.leg_dir, 1)
check_close("leg high is the day's high", s.leg_high, 5020)
check_close("leg low is the day's low", s.leg_low, 4990)
check("the leg is described as the day's range", s.fib_leg_note, "the day's range")

print("\n--- a low made after the high is a down leg, sold on the bounce ---")
eng = engine(fib_anchor_minutes=15)
feed(eng, [bar(0, 5005, 5000), bar(2, 5020, 5010), bar(12, 5004, 4990),
           bar(15, 5000, 4995)])
check("direction is down — the low printed last", eng.session.leg_dir, -1)
check_close("leg spans the whole day range", eng.session.leg_high - eng.session.leg_low, 30)

print("\n--- the day's extremes are tracked from the bell, not from the anchor time ---")
eng = engine(fib_anchor_minutes=15)
feed(eng, [bar(0, 5100, 4900), bar(16, 5010, 5000)])
check_close("high from the first bar is kept", eng.session.day_high, 5100)
check_close("low from the first bar is kept", eng.session.day_low, 4900)

print("\n--- with --fib-anchor-extend a new extreme extends the leg and re-arms the setup ---")
eng = engine(fib_anchor_minutes=15, fib_anchor_extend=True)
feed(eng, [bar(0, 5005, 5000), bar(2, 5004, 4990), bar(12, 5020, 5010), bar(15, 5015, 5011)])
eng.session.leg_dir = 0                      # an attempt was already taken off this leg
feed(eng, [bar(20, 5030, 5025)])             # ... then the day makes a higher high
s = eng.session
check_close("leg high follows the day to the new extreme", s.leg_high, 5030)
check("the setup is armed again", s.leg_dir, 1)
check("and the leg says so", s.fib_leg_note, "the day's range, extended to a new extreme")

print("\n--- the live rule keeps the leg the 15-minute one ---")
eng = engine(fib_anchor_minutes=15)
feed(eng, [bar(0, 5005, 5000), bar(2, 5004, 4990), bar(12, 5020, 5010), bar(15, 5015, 5011)])
eng.session.leg_dir = 0
feed(eng, [bar(20, 5030, 5025)])
check_close("leg high stays where it was anchored", eng.session.leg_high, 5020)
check("no second attempt off a new extreme", eng.session.leg_dir, 0)

print("\n--- the pivot anchor is untouched by any of this ---")
eng = pe.PaperEngine(rules.load_config(), or_minutes=3, exit_rule="scale_2R", verbose=False,
                     setups=("fib",), pivot_len=2, min_leg_pts=6.0)
eng.session = pe.Session(date="2026-01-05")
shape = [5010, 5000, 4990, 5000, 5010, 5015, 5018, 5020, 5030, 5020, 5015, 5010]
for m, px in enumerate(shape):
    b = bar(m, px + 1, px - 1, px)
    eng.session.bars_seen.append(b)
    eng._track_day_range(b)
    eng._anchor_pivots(b)
s = eng.session
check("a swing low and a swing high make a leg", s.leg_dir != 0, True)
check("the leg is a pivot leg", s.fib_leg_note, "swing pivots")
check("and the day-range fields play no part in it", s.fib_anchored, False)

print("\n--- the .618 entry, stop and target come off whichever leg was anchored ---")
eng = engine(fib_anchor_minutes=15)
feed(eng, [bar(0, 5005, 5000), bar(2, 5004, 4990), bar(12, 5020, 5010), bar(15, 5015, 5011)])
s = eng.session
leg = s.leg_high - s.leg_low
check_close("the .618 of a 30-point up leg", s.leg_high - leg * 0.618, 5001.46)
taken: list[tuple] = []
eng._try_entry = lambda b, side, entry, stop, setup, target_override=None: taken.append(
    (side, entry, stop, target_override))
b = bar(20, 5003, 5000, 5000)                # the pullback touches the zone
eng.session.bars_seen.append(b)
eng._fib_signal(b)
check("a touch alone is not an entry", taken, [])
# then a bullish close back out of the zone
b = pe.Bar(ts=OPEN + timedelta(minutes=21), open=5002, high=5006, low=5001, close=5005)
eng.session.bars_seen.append(b)
eng._fib_signal(b)
check("the confirming close is the entry", len(taken), 1)
if taken:
    side, entry, stop, target = taken[0]
    check("bought, because the leg is up", side, "long")
    check_close("entered at the close", entry, 5005)
    check_close("stop is just past the far end of the leg", stop, 4989.75)
    # 30-point leg: 0.272 x 30 = 8.16, rounded up to the 0.25 tick grid
    check_close("target is the 1.272 extension of the leg, on the tick grid", target, 5028.25)

print("\n--- --fib-target 1.0 puts the target back on the leg extreme ---")
eng = engine(fib_anchor_minutes=15, fib_target_ext=1.0)
feed(eng, [bar(0, 5005, 5000), bar(2, 5004, 4990), bar(12, 5020, 5010), bar(15, 5015, 5011)])
taken = []
eng._try_entry = lambda b, side, entry, stop, setup, target_override=None: taken.append(
    (side, entry, stop, target_override))
for b in (bar(20, 5003, 5000, 5000),
          pe.Bar(ts=OPEN + timedelta(minutes=21), open=5002, high=5006, low=5001, close=5005)):
    eng.session.bars_seen.append(b)
    eng._fib_signal(b)
check_close("target is the leg extreme itself", taken[0][3] if taken else None, 5020)

print("\n" + ("ALL FIB ANCHOR CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
