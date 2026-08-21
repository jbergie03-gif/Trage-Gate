"""Bar-by-bar checks on the exit rules — the part of the engine that decides what a
trade keeps.

Every rule is driven with a hand-built sequence of bars whose shape is the thing being
asserted: a trade that runs 1.2R and comes back, a trade that runs to target, a short
doing the same, and a bar that covers both the stop and the target. The journal here is a
throwaway file, so nothing touches paper_journal.db.

    python test_exits.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TMP = Path(tempfile.mkdtemp(prefix="exit-tests-"))
os.environ["TRADE_GATE_DB"] = str(TMP / "journal.db")
os.environ["TRADE_GATE_REPORTS"] = str(TMP / "reports")

import paper_engine as pe  # noqa: E402
import rules  # noqa: E402

CT = ZoneInfo("America/Chicago")
fails: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


def check_close(name: str, got: float, want: float, tol: float = 0.01) -> None:
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got:.2f}" + ("" if ok else f" (want {want:.2f})"))
    if not ok:
        fails.append(name)


def engine(exit_rule: str, **kw) -> pe.PaperEngine:
    cfg = rules.load_config()
    eng = pe.PaperEngine(cfg, or_minutes=2, exit_rule=exit_rule, verbose=False,
                         runner_pct=0.25, **kw)
    eng.session = pe.Session(date="2026-01-05")
    return eng


def position(eng: pe.PaperEngine, side: str, entry: float, r_pts: float,
             contracts: int = 4, setup: str = "ORB") -> pe.Position:
    """Open a position straight into the throwaway journal, skipping the setup logic."""
    stop = entry - r_pts if side == "long" else entry + r_pts
    tgt_r = eng.scale_r or 2.0
    target = entry + r_pts * tgt_r if side == "long" else entry - r_pts * tgt_r
    with rules.db() as conn:
        cur = conn.execute(
            "INSERT INTO trades (staged_at, trade_date, account, instrument, side, entry, "
            "stop, target, contracts, risk_dollars, reward_dollars, setup, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-01-05T08:30:00", "2026-01-05", "100K", "MES", side, entry, stop, target,
             contracts, 150.0, 300.0, f"test {setup}", "simulated"))
        conn.commit()
    eng.pos = pe.Position(side=side, entry=entry, stop=stop, target=target,
                          contracts=contracts, opened=datetime(2026, 1, 5, 8, 30, tzinfo=CT),
                          trade_id=cur.lastrowid, r_points=r_pts, setup=setup,
                          best=entry, trail=stop)
    return eng.pos


def feed(eng: pe.PaperEngine, bars: list[tuple[float, float, float, float]]) -> dict | None:
    """Push bars through the exit logic until it closes the trade; return that trade."""
    t = datetime(2026, 1, 5, 8, 31, tzinfo=CT)
    for i, (o, h, lo, c) in enumerate(bars):
        if eng.pos is None:
            break
        eng._manage(pe.Bar(ts=t + timedelta(minutes=i), open=o, high=h, low=lo, close=c))
    trades = eng.session.trades
    return trades[-1] if trades else None


# A trade that runs 1.2R and hands it all back — the 2026-08-20 shape, twice over.
GAVE_IT_BACK = [(100, 110, 99, 108), (108, 112, 106, 107), (107, 108, 88, 90)]
# The same start, but it keeps going through 2R.
RAN_TO_TARGET = [(100, 110, 99, 108), (108, 112, 106, 110), (110, 125, 109, 124)]


# `pe.write_state` writes paper_state.json next to the engine; the tests only care about
# the exit decision, so it is stubbed out.
pe.write_state = lambda *a, **k: None  # type: ignore[assignment]

print("--- scale_2R: unchanged by the new options ---")
eng = engine("scale_2R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, GAVE_IT_BACK)
check("2R: 1.2R then reversal is a full stop", t["why"], "stop")
check_close("2R: exits at the original stop", t["exit"], 90.0)
eng = engine("scale_2R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, RAN_TO_TARGET + [(124, 125, 116, 118), (118, 119, 110, 111)])
check("2R: target scales out and leaves a runner", t["why"], "2R scale-out, runner stop")
check("2R: the runner is a quarter of 4 contracts", t["contracts"], 1)
check_close("2R: the runner trails an R behind the 125 high", t["exit"], 115.0)

print("\n--- scale_1.5R: the same rule, nearer target ---")
eng = engine("scale_1.5R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, [(100, 110, 99, 108), (108, 116, 107, 115), (115, 116, 100, 101)])
check("1.5R: scales at 1.5R, not 2R", t["why"], "1.5R scale-out, runner stop")
check("1.5R: runner left on", t["contracts"], 1)
eng = engine("scale_1.5R")
position(eng, "long", 100.0, 10.0)
check_close("1.5R: target sits 1.5R above entry", eng.pos.target, 115.0)
t = feed(eng, GAVE_IT_BACK)
check("1.5R: 1.2R is still not enough", t["why"], "stop")

print("\n--- be_1R: a full R makes the trade unloseable ---")
eng = engine("be_1R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, GAVE_IT_BACK)
check("be_1R: exits at breakeven, not the stop", t["why"], "stop")
check_close("be_1R: exit is the entry price", t["exit"], 100.0)
check_close("be_1R: so the trade is flat before fees", t["points"], 0.0)
eng = engine("be_1R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, RAN_TO_TARGET)
check("be_1R: a winner still runs to its 2R target", t["why"], "target")
check_close("be_1R: whole position off at 2R", t["exit"], 120.0)
check("be_1R: nothing scaled", t["contracts"], 4)
eng = engine("be_1R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, [(100, 105, 99, 104), (104, 105, 90, 91)])
check("be_1R: half an R does not move the stop", t["why"], "stop")
check_close("be_1R: full loss taken", t["exit"], 90.0)

print("\n--- be_1R short side ---")
eng = engine("be_1R")
position(eng, "short", 100.0, 10.0)
t = feed(eng, [(100, 101, 90, 92), (92, 94, 91, 93), (93, 112, 92, 110)])
check("be_1R short: stopped at breakeven", t["why"], "stop")
check_close("be_1R short: exit is the entry price", t["exit"], 100.0)
eng = engine("be_1R")
position(eng, "short", 100.0, 10.0)
t = feed(eng, [(100, 101, 90, 92), (92, 93, 79, 80)])
check("be_1R short: winner reaches 2R", t["why"], "target")
check_close("be_1R short: exit at 2R below entry", t["exit"], 80.0)

print("\n--- trail_after_1R and --trail-r ---")
eng = engine("trail_after_1R")
position(eng, "long", 100.0, 10.0)
t = feed(eng, [(100, 115, 99, 114), (114, 116, 104, 105)])
check_close("trail 1R: stop follows an R behind the 116 high", t["exit"], 105.0)
eng = engine("trail_after_1R", trail_r=0.5)
position(eng, "long", 100.0, 10.0)
t = feed(eng, [(100, 115, 99, 114), (114, 116, 104, 105)])
check_close("trail 0.5R: stop follows half an R behind", t["exit"], 110.0)
eng = engine("trail_after_1R", trail_r=0.5)
position(eng, "short", 100.0, 10.0)
t = feed(eng, [(100, 101, 85, 86), (86, 96, 85, 95)])
check_close("trail 0.5R short: stop half an R above the low", t["exit"], 90.0)

print("\n--- an ambiguous bar is always scored as the stop ---")
for rule, want in [("scale_2R", "stop"), ("scale_1.5R", "stop"), ("be_1R", "stop")]:
    eng = engine(rule)
    position(eng, "long", 100.0, 10.0)
    t = feed(eng, [(100, 130, 88, 95)])
    check(f"{rule}: bar covering stop and target is a stop", t["why"], want)
    check_close(f"{rule}: filled at the stop", t["exit"], 90.0)

print("\n--- the scale multiple each rule name means ---")
check("scale_2R banks at 2R", pe.SCALE_RULES["scale_2R"], 2.0)
check("scale_1.5R banks at 1.5R", pe.SCALE_RULES["scale_1.5R"], 1.5)
check("be_1R is not a scaling rule", pe.SCALE_RULES.get("be_1R"), None)
check("the CLI offers every rule tested here",
      {"scale_2R", "scale_1.5R", "be_1R", "trail_after_1R"}
      <= set(pe.EXIT_RULES), True)

print("\n--- the daily comparison cannot touch the journal it compares against ---")
csv = Path("data/SP500_1min_deep.csv")
if csv.exists():
    import hashlib
    cfg = rules.load_config()
    bars = [b for b in pe.replay_bars(str(csv))
            if b.ts.strftime("%Y-%m-%d") == "2026-08-14"]
    kw = dict(runner_pct=0.25, orb_reentry=True)
    live = pe.PaperEngine(cfg, 2, "scale_2R", verbose=False, **kw)
    for b in bars:
        live.on_bar(b)
    live._close_session()
    db = Path(os.environ["TRADE_GATE_DB"])
    before = hashlib.md5(db.read_bytes()).hexdigest()
    reports_before, state_before = pe.REPORT_DIR, pe.STATE_FILE
    table = pe.compare_exits(cfg, bars, live, ["scale_1.5R", "be_1R", "trail_after_1R"], **kw)
    check("journal is byte-identical afterwards", hashlib.md5(db.read_bytes()).hexdigest(),
          before)
    check("report directory is put back", pe.REPORT_DIR, reports_before)
    check("state file is put back", pe.STATE_FILE, state_before)
    for rule in ("scale_2R (live, the record)", "scale_1.5R", "be_1R", "trail_after_1R"):
        check(f"table has a row for {rule}", f"`{rule}`" in table, True)
else:
    print(f"  skip  {csv} is not in this checkout")

print("\n" + ("ALL EXIT CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
