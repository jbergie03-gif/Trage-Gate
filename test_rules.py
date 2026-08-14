"""End-to-end checks on the rule engine: sizing, lockouts, and the payout gates.

Every expected number here is derived from Apex's published EOD tables, so a
failure means either the engine or the config drifted from Apex's actual rules.
"""
import os
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import rules

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
fails = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r} want {want!r}")
    if not ok:
        fails.append(name)


def check_true(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    rules.DB_PATH = path
    return rules.db()


def log_day(conn, d, pnl, account="100K"):
    """Insert one closed trade representing a day's P&L."""
    when = datetime(2026, 8, 13, 9, 45, tzinfo=CT)
    conn.execute(
        "INSERT INTO trades (staged_at, trade_date, account, instrument, side, entry, stop, target,"
        " contracts, risk_dollars, reward_dollars, setup, exit_price, pnl, closed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (when.isoformat(), d, account, "MES", "long", 5000.0, 4994.0, 5012.0,
         5, 150.0, 300.0, "test", 5000 + pnl / 25, pnl, when.isoformat()),
    )
    conn.commit()


cfg = rules.load_config()
cfg["active_account"] = "100K"
cfg["instrument"] = "MES"
mid = datetime(2026, 8, 13, 9, 30, tzinfo=CT)
late = datetime(2026, 8, 13, 15, 10, tzinfo=CT)

print("\n--- 100K EOD PA limits (all from Apex's tables) ---")
lim = rules.limits(cfg)
check("eod drawdown", lim.eod_drawdown, 3000.0)
check("apex DLL", lim.apex_daily_loss_limit, 1500.0)
check("min daily profit to qualify", lim.min_daily_profit, 300.0)
check("safety net in profit terms (103,100-100,000)", lim.safety_net_profit, 3100.0)
check("profit needed to request (103,600-100,000)", lim.profit_to_first_request, 3600.0)
check("first payout cap", lim.next_payout_cap, 2000.0)
check("max contracts MES (8 ES x10)", lim.max_contracts, 80)
check("risk per trade (5% of 3000)", lim.risk_per_trade, 150.0)
check("my daily stop (15% of 3000)", lim.max_daily_loss, 450.0)
check("daily target ($300 min + $25 buffer)", lim.daily_target, 325.0)
check("R:R one trade needs to finish the day", lim.rr_for_one_trade_day, 2.17)
check_true("target clears Apex's qualifying minimum", lim.daily_target >= lim.min_daily_profit)
check_true("daily stop tighter than Apex DLL", lim.max_daily_loss < lim.apex_daily_loss_limit)
cfg["instrument"] = "ES"
check("max contracts ES", rules.limits(cfg).max_contracts, 8)
cfg["instrument"] = "MES"

print("\n--- payout cap schedule (100K: 2000/2500/2500/3000/4000/4000) ---")
for n, want in enumerate([2000.0, 2500.0, 2500.0, 3000.0, 4000.0, 4000.0]):
    check(f"payout #{n+1} cap", rules.limits(cfg, payouts_taken=n).next_payout_cap, want)
check("caps stop at the 6th", rules.limits(cfg, payouts_taken=9).next_payout_cap, 4000.0)

print("\n--- sizing ---")
s = rules.size_trade(cfg, "long", 5000.0, 4994.0, 5012.0)
check("6pt stop -> 5 MES ($150 cap / $30 per contract)", s["contracts"], 5)
check("risk dollars", s["risk_dollars"], 150.0)
check("reward:risk", s["reward_to_risk"], 2.0)
check_true("valid trade accepted", s["ok"])
check("commission on 5 MES", s["commission"], 6.2)
check("net if target hit", s["net_if_target_hit"], 293.8)
check("net if stopped", s["net_if_stopped"], -156.2)
check_true("a 2:1 winner does NOT reach a qualifying day net of fees",
           not s["makes_qualifying_day"], f"net {s['net_if_target_hit']}")
big = rules.size_trade(cfg, "long", 5000.0, 4994.0, 5015.0)  # 3.5:1
check_true("a 3.5:1 winner does make a qualifying day", big["makes_qualifying_day"],
           f"net {big['net_if_target_hit']}")
check_true("and it finishes the daily target", big["net_if_target_hit"] >= lim.daily_target)

check_true("1:1 rejected", not rules.size_trade(cfg, "long", 5000, 4994, 5006)["ok"])
check_true("20pt stop rejected", not rules.size_trade(cfg, "long", 5000, 4980, 5040)["ok"])
check_true("inverted stop rejected", not rules.size_trade(cfg, "long", 5000, 5006, 5012)["ok"])
check_true("target behind entry rejected", not rules.size_trade(cfg, "long", 5000, 4994, 4990)["ok"])
check_true("bad side rejected", not rules.size_trade(cfg, "sideways", 5000, 4994, 5012)["ok"])
short = rules.size_trade(cfg, "short", 5000.0, 5006.0, 4988.0)
check_true("short accepted", short["ok"], short["errors"])
check("short sizing", short["contracts"], 5)
cfg["instrument"] = "ES"
check_true("ES 6pt stop too big for the per-trade cap",
           not rules.size_trade(cfg, "long", 5000, 4994, 5012)["ok"])
es = rules.size_trade(cfg, "long", 5000.0, 4997.5, 5006.25)  # 2.5pt stop = $125
check_true("ES works with a tight stop", es["ok"], es["errors"])
check("ES contracts", es["contracts"], 1)
cfg["instrument"] = "MES"

print("\n--- session window ---")
conn = fresh_db()
st = rules.evaluate(cfg, conn, when=mid)
check_true("cleared to trade at 09:30 CT", st["can_trade"], st["blocks"])
check("fresh buffer = full drawdown", st["account"]["buffer_to_threshold"], 3000.0)
check_true("no false threshold warning when fresh",
           not any("above the EOD threshold" in w for w in st["warnings"]))
check_true("MAE not enforced", not st["mae"]["enforced"])
check_true("blocked at 13:00 CT",
           not rules.evaluate(cfg, conn, when=datetime(2026, 8, 13, 13, 0, tzinfo=CT))["can_trade"])

print("\n--- red-day lockouts ---")
conn = fresh_db()
log_day(conn, "2026-08-13", -150.0)
log_day(conn, "2026-08-13", -150.0)
st = rules.evaluate(cfg, conn, when=mid)
check_true("two consecutive losses locks the day", not st["can_trade"])
check_true("consecutive-loss reason", any("consecutive losses" in b for b in st["blocks"]))

conn = fresh_db()
log_day(conn, "2026-08-13", -460.0)
st = rules.evaluate(cfg, conn, when=mid)
check_true("daily stop message", any("DAILY STOP" in b for b in st["blocks"]), st["blocks"])
check("loss budget floors at 0", st["day"]["loss_budget_remaining"], 0.0)

conn = fresh_db()
log_day(conn, "2026-08-13", -100.0)
log_day(conn, "2026-08-13", 50.0)
log_day(conn, "2026-08-13", -100.0)
st = rules.evaluate(cfg, conn, when=mid)
check("realized", st["day"]["realized"], -150.0)
check("loss budget left", st["day"]["loss_budget_remaining"], 300.0)
check_true("3-trade cap", any("Trade count cap" in b for b in st["blocks"]))

print("\n--- green lockout (the anti-greed rule) ---")
conn = fresh_db()
log_day(conn, "2026-08-13", 330.0)
st = rules.evaluate(cfg, conn, when=mid)
check_true("target hit locks the day", not st["can_trade"])
check_true("target message frames it as a win",
           any("TARGET HIT" in b and "WIN" in b for b in st["blocks"]), st["blocks"])
check_true("the day counts as qualifying", st["day"]["qualifies"])
conn = fresh_db()
log_day(conn, "2026-08-13", 250.0)  # under Apex's $300 minimum
st = rules.evaluate(conn=conn, cfg=cfg, when=mid)
check_true("a $250 day does NOT qualify on a 100K", not st["day"]["qualifies"])
check_true("still allowed to keep working toward $300", st["can_trade"], st["blocks"])
check("consistency cap floors at the daily target, never below",
      st["day"]["consistency_cap"], 325.0)

print("\n--- 50% consistency ---")
check("no history: cap is whatever floor is given", rules.day_cap(0, 0, 0.5, floor=325), 325.0)
check("cap after $1000 of other days", rules.day_cap(1000, 400, 0.5), 1000.0)
check("cap never below the existing best day", rules.day_cap(100, 400, 0.5), 400.0)
conn = fresh_db()
for d, p in [("2026-08-05", 400.0), ("2026-08-06", 350.0), ("2026-08-07", 400.0)]:
    log_day(conn, d, p)
st = rules.evaluate(cfg, conn, when=mid)
check("cycle total", st["account"]["cycle_total"], 1150.0)
check("best day share 400/1150", st["account"]["best_day_share"], 0.3478)
check_true("consistency satisfied", st["payout"]["consistency_ok"])
check("today's consistency cap", st["day"]["consistency_cap"], 1150.0)

conn = fresh_db()
log_day(conn, "2026-08-05", 300.0)
log_day(conn, "2026-08-06", 2000.0)  # outlier: 87% of profit
st = rules.evaluate(cfg, conn, when=mid)
check_true("outlier breaks consistency", not st["payout"]["consistency_ok"])
check_true("payout blocked with a stated fix",
           any("more profit spread over other days" in m for m in st["payout"]["missing"]),
           st["payout"]["missing"])

print("\n--- payout eligibility: the whole point ---")
conn = fresh_db()
# Five qualifying days but not enough total profit yet.
for i in range(5):
    log_day(conn, f"2026-08-{10+i:02d}", 400.0)
st = rules.evaluate(cfg, conn, when=mid)
check("qualifying days", st["payout"]["qualifying_days"], 5)
check_true("not yet eligible on $2,000", not st["payout"]["eligible"])
check_true("tells him exactly what is short",
           any("more profit" in m for m in st["payout"]["missing"]), st["payout"]["missing"])

conn = fresh_db()
for i in range(9):  # nine $400 days = $3,600
    log_day(conn, f"2026-08-{10+i:02d}", 400.0)
st = rules.evaluate(cfg, conn, when=mid)
check("total profit", st["account"]["total"], 3600.0)
check("balance", st["account"]["balance"], 103600.0)
check_true("ELIGIBLE at nine $400 days", st["payout"]["eligible"], st["payout"]["missing"])
check("withdrawable above safety net", st["payout"]["withdrawable_above_safety_net"], 500.0)
check("request amount capped by withdrawable", st["payout"]["request_amount"], 500.0)
check_true("payout-available warning fires",
           any("PAYOUT AVAILABLE" in w for w in st["warnings"]), st["warnings"])

# Deeper account: the request is capped by the payout schedule, not the balance.
conn = fresh_db()
for i in range(20):
    log_day(conn, f"2026-08-{i+1:02d}", 400.0)  # $8,000
st = rules.evaluate(cfg, conn, when=mid)
check("withdrawable", st["payout"]["withdrawable_above_safety_net"], 4900.0)
check("capped at payout #1 max", st["payout"]["request_amount"], 2000.0)

print("\n--- payout resets the consistency cycle ---")
conn.execute(
    "INSERT INTO payouts (account, requested_on, amount, approved) VALUES (?,?,?,?)",
    ("100K", "2026-08-15", 2000.0, 1),
)
conn.commit()
st = rules.evaluate(cfg, conn, when=mid)
check("lifetime total unchanged", st["account"]["total"], 8000.0)
check("cycle counts only post-payout days", st["account"]["cycle_days"], 5)
check("cycle total", st["account"]["cycle_total"], 2000.0)
check("next payout cap steps to #2", st["limits"]["next_payout_cap"], 2500.0)
check("payouts taken", st["limits"]["payouts_taken"], 1)

print("\n--- EOD threshold ---")
conn = fresh_db()
log_day(conn, "2026-08-10", 1000.0)
log_day(conn, "2026-08-11", 500.0)   # high-water 1500
log_day(conn, "2026-08-12", -200.0)
st = rules.evaluate(cfg, conn, when=mid)
check("eod high", st["account"]["eod_high"], 1500.0)
check("threshold trails the high", st["account"]["eod_threshold"], -1500.0)
check("buffer", st["account"]["buffer_to_threshold"], 2800.0)
conn = fresh_db()
log_day(conn, "2026-08-10", 2900.0)
log_day(conn, "2026-08-11", -2600.0)  # threshold now -100, balance +300
st = rules.evaluate(cfg, conn, when=mid)
check("buffer", st["account"]["buffer_to_threshold"], 400.0)
check_true("warns when under one daily stop from failure",
           any("above the EOD threshold" in w for w in st["warnings"]), st["warnings"])

print("\n--- flatten before the close ---")
conn = fresh_db()
conn.execute(
    "INSERT INTO trades (staged_at, trade_date, account, instrument, side, entry, stop, target,"
    " contracts, risk_dollars, reward_dollars, setup) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    (late.isoformat(), "2026-08-13", "100K", "MES", "long", 5000.0, 4994.0, 5012.0,
     5, 150.0, 300.0, "test"),
)
conn.commit()
st = rules.evaluate(cfg, conn, when=late)
check_true("open trade blocks a new one", any("still open" in b for b in st["blocks"]))
check_true("flatten warning", any("FLATTEN NOW" in w for w in st["warnings"]), st["warnings"])

print("\n--- 6PM ET rollover ---")
check("17:00 ET is today",
      rules.trade_date(datetime(2026, 8, 13, 17, 0, tzinfo=ET)), "2026-08-13")
check("19:00 ET is tomorrow's session",
      rules.trade_date(datetime(2026, 8, 13, 19, 0, tzinfo=ET)), "2026-08-14")

print("\n--- every account size ---")
for size, min_daily, net, req, cap1, risk, stop, tgt in [
    ("25K", 100.0, 1100.0, 1600.0, 1000.0, 50.0, 150.0, 125.0),
    ("50K", 250.0, 2100.0, 2600.0, 1500.0, 100.0, 300.0, 275.0),
    ("100K", 300.0, 3100.0, 3600.0, 2000.0, 150.0, 450.0, 325.0),
    ("150K", 350.0, 4100.0, 4600.0, 2500.0, 200.0, 600.0, 375.0),
]:
    cfg["active_account"] = size
    L = rules.limits(cfg)
    check(f"{size} min daily profit", L.min_daily_profit, min_daily)
    check(f"{size} safety net (profit)", L.safety_net_profit, net)
    check(f"{size} profit to request", L.profit_to_first_request, req)
    check(f"{size} first payout cap", L.next_payout_cap, cap1)
    check(f"{size} risk/trade", L.risk_per_trade, risk)
    check(f"{size} daily stop", L.max_daily_loss, stop)
    check(f"{size} daily target", L.daily_target, tgt)
    check_true(f"{size} target qualifies for a payout day", L.daily_target >= L.min_daily_profit)
    check_true(f"{size} daily stop <= Apex DLL", L.max_daily_loss <= L.apex_daily_loss_limit)
    check_true(f"{size} one loss cannot approach the drawdown",
               L.risk_per_trade <= L.eod_drawdown * 0.05)
    check_true(f"{size} one trade can finish a day at a sane R:R",
               L.rr_for_one_trade_day <= 3.0, f"needs {L.rr_for_one_trade_day}:1")
    days = req / L.daily_target
    check_true(f"{size} first payout inside 15 target days", days <= 15, f"{days:.1f} days")

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
