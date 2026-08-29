"""Risk and rule engine for the trade gate.

Every Apex figure comes from config.json and is verified against Apex's own
help-center pages. Nothing here talks to a broker or places an order — Apex
prohibits automation. The engine decides whether a trade may be staged, how
large it may be, and when the day is over.

The core idea: on a funded EOD account you do not need a big number. On a 100K
you need +$3,600 and five days of at least $300. So the daily target is a
CEILING, and hitting it closes the platform for the day.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
# TRADE_GATE_DB keeps simulated runs out of the real journal. The paper engine sets it.
DB_PATH = Path(os.environ.get("TRADE_GATE_DB", BASE / "journal.db"))
CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
# Everything Jonathan reads is Pacific. Exchange time still defines the session — the open is
# an exchange event — so the rules are stored in CT and only ever displayed in PT.
PT = ZoneInfo("America/Los_Angeles")


def pt(ts: datetime) -> str:
    """A timestamp as Jonathan's clock reads it."""
    return ts.astimezone(PT).strftime("%H:%M")


def ct_to_pt(hhmm: str, on: datetime | None = None) -> str:
    """A stored CT rule time ("08:30") as Pacific ("06:30"), DST-correct for the day."""
    h, m = (int(x) for x in hhmm.split(":"))
    day = (on or datetime.now(CT)).astimezone(CT)
    return day.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(PT).strftime("%H:%M")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staged_at TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    account TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    contracts INTEGER NOT NULL,
    risk_dollars REAL NOT NULL,
    reward_dollars REAL NOT NULL,
    setup TEXT,
    exit_price REAL,
    pnl REAL,
    closed_at TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    blocked_reason TEXT NOT NULL,
    justification TEXT
);
CREATE TABLE IF NOT EXISTS payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    requested_on TEXT NOT NULL,
    amount REAL NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0
);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_ct() -> datetime:
    return datetime.now(CT)


def trade_date(dt: datetime | None = None) -> str:
    """Apex's trading day resets at 6:00 PM ET, so evening trades belong to tomorrow."""
    dt = dt or now_ct()
    et = dt.astimezone(ET)
    if et.hour >= 18:
        et += timedelta(days=1)
    return et.strftime("%Y-%m-%d")


def _parse_ct(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


@dataclass
class Limits:
    account: str
    instrument: str
    start_balance: float
    eod_drawdown: float
    apex_daily_loss_limit: float
    max_contracts: int
    # Apex payout gates
    min_daily_profit: float
    safety_net_profit: float
    profit_to_first_request: float
    next_payout_cap: float
    payouts_taken: int
    max_payouts: int
    # my rules
    risk_per_trade: float
    max_daily_loss: float
    daily_target: float
    tick_value: float
    point_value: float
    commission_round_trip: float
    rr_for_one_trade_day: float


def limits(cfg: dict, payouts_taken: int = 0) -> Limits:
    acct_name = cfg["active_account"]
    a = cfg["accounts"][acct_name]
    inst_name = cfg["instrument"]
    inst = cfg["instruments"][inst_name]
    r = cfg["my_rules"]
    start = float(a["start_balance"])
    drawdown = float(a["eod_drawdown"])
    apex_dll = float(a["daily_loss_limit"])
    min_daily = float(a["min_daily_profit"])
    schedule = a["max_payouts_schedule"]
    # My daily stop is a fraction of the drawdown and always tighter than Apex's DLL,
    # because Apex's DLL only pauses the session — it does not protect the account.
    my_daily_loss = round(drawdown * r["max_daily_loss_pct_of_drawdown"], 2)
    risk = round(drawdown * r["risk_per_trade_pct_of_drawdown"], 2)
    commission = float(inst["commission_round_trip"])
    target = round(min_daily + r["daily_target_buffer_over_min"], 2)
    return Limits(
        account=acct_name,
        instrument=inst_name,
        start_balance=start,
        eod_drawdown=drawdown,
        apex_daily_loss_limit=apex_dll,
        max_contracts=int(a["max_contracts_es"]) * int(inst["contract_ratio"]),
        min_daily_profit=min_daily,
        safety_net_profit=round(float(a["safety_net_balance"]) - start, 2),
        profit_to_first_request=round(float(a["min_balance_to_request"]) - start, 2),
        next_payout_cap=float(schedule[min(payouts_taken, len(schedule) - 1)]),
        payouts_taken=payouts_taken,
        max_payouts=int(cfg["payout"]["max_payouts"]),
        risk_per_trade=risk,
        max_daily_loss=min(my_daily_loss, apex_dll),
        daily_target=target,
        tick_value=float(inst["tick_value"]),
        point_value=float(inst["point_value"]),
        commission_round_trip=commission,
        # Reward:risk one trade needs to finish the day by itself (before commissions,
        # which size_trade nets out exactly once the stop width is known).
        rr_for_one_trade_day=round(target / risk, 2) if risk else 0.0,
    )


@dataclass
class DayState:
    date: str
    trades: list = field(default_factory=list)
    open_trade: dict | None = None
    realized: float = 0.0
    wins: int = 0
    losses: int = 0
    consecutive_losses: int = 0
    last_loss_at: datetime | None = None


def day_state(conn: sqlite3.Connection, account: str, d: str | None = None) -> DayState:
    d = d or trade_date()
    rows = conn.execute(
        "SELECT * FROM trades WHERE trade_date=? AND account=? ORDER BY id", (d, account)
    ).fetchall()
    st = DayState(date=d)
    for row in rows:
        t = dict(row)
        st.trades.append(t)
        if t["pnl"] is None:
            st.open_trade = t
            continue
        st.realized += t["pnl"]
        if t["pnl"] > 0:
            st.wins += 1
            st.consecutive_losses = 0
        elif t["pnl"] < 0:
            st.losses += 1
            st.consecutive_losses += 1
            st.last_loss_at = datetime.fromisoformat(t["closed_at"])
        else:
            st.consecutive_losses = 0
    return st


def payouts_taken(conn: sqlite3.Connection, account: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM payouts WHERE account=? AND approved=1", (account,)
    ).fetchone()
    return int(row["n"])


def last_payout_date(conn: sqlite3.Connection, account: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(requested_on) AS d FROM payouts WHERE account=? AND approved=1", (account,)
    ).fetchone()
    return row["d"]


def account_totals(
    conn: sqlite3.Connection,
    account: str,
    min_daily_profit: float,
    since: str | None = None,
    today: str | None = None,
) -> dict:
    """Per-day P&L for the account, plus the numbers the payout rules are judged on.

    `since` is the last approved payout date: the 50% consistency test is measured
    on profit earned since then, not over the account's whole life.
    """
    rows = conn.execute(
        "SELECT trade_date, SUM(pnl) AS pnl FROM trades WHERE account=? AND pnl IS NOT NULL "
        "GROUP BY trade_date ORDER BY trade_date",
        (account,),
    ).fetchall()
    days = [{"date": r["trade_date"], "pnl": round(r["pnl"] or 0.0, 2)} for r in rows]
    total = round(sum(d["pnl"] for d in days), 2)

    # Highest closing balance reached: what the EOD threshold trails.
    running = 0.0
    eod_high = 0.0
    for d in days:
        running += d["pnl"]
        eod_high = max(eod_high, running)

    cycle = [d for d in days if since is None or d["date"] > since]
    cycle_total = round(sum(d["pnl"] for d in cycle), 2)
    qualifying = [d for d in cycle if d["pnl"] >= min_daily_profit]
    best = max((d["pnl"] for d in cycle if d["pnl"] > 0), default=0.0)
    # The consistency cap for today must be judged against the OTHER days in the
    # cycle, otherwise today's own profit inflates the cap it is measured against.
    today = today or trade_date()
    prior = [d for d in cycle if d["date"] != today]
    return {
        "days": days,
        "total": total,
        "trading_days": len(days),
        "eod_high": round(eod_high, 2),
        "cycle_total": cycle_total,
        "cycle_days": len(cycle),
        "qualifying_days": len(qualifying),
        "best_day": round(best, 2),
        "best_day_share": round(best / cycle_total, 4) if cycle_total > 0 else 0.0,
        "prior_days_total": round(sum(d["pnl"] for d in prior), 2),
        "prior_best_day": round(max((d["pnl"] for d in prior if d["pnl"] > 0), default=0.0), 2),
    }


def day_cap(prior_total: float, prior_best_day: float, pct: float, floor: float = 0.0) -> float:
    """Largest profit today may be without tripping the consistency rule.

    Apex requires best_day < pct * total_profit_since_last_payout. If today
    becomes the new best day, x < pct*(prior_total + x), which solves to
    x < pct*prior_total/(1-pct). Matching the existing best day is always safe,
    so that is one floor; `floor` (the daily target) is the other, because early
    in a cycle the formula yields a tiny number and the target lock already
    stops the day — consistency is only tested when a payout is requested.
    """
    if pct >= 1:
        return float("inf")
    return round(max(pct * prior_total / (1 - pct), prior_best_day, floor), 2)


def mae_ceiling(cfg: dict, start_of_day_profit: float, eod_drawdown: float) -> float:
    """Apex's legacy MAE cap. Reference only unless mae.enforce is true."""
    m = cfg["mae"]
    floor = m["pct_low_profit_basis_of_drawdown"] * eod_drawdown
    return round(max(m["pct_of_profit"] * start_of_day_profit, floor), 2)


def payout_status(lim: Limits, tot: dict, pay: dict) -> dict:
    """What still stands between the account and a payout request."""
    missing = []
    days_left = max(0, pay["min_qualifying_days"] - tot["qualifying_days"])
    if days_left:
        missing.append(
            f"{days_left} more qualifying day(s) of >= ${lim.min_daily_profit:,.0f} net"
        )
    profit_left = round(lim.profit_to_first_request - tot["total"], 2)
    if profit_left > 0:
        missing.append(f"${profit_left:,.2f} more profit (need +${lim.profit_to_first_request:,.0f})")
    consistency_ok = (
        tot["cycle_total"] <= 0 or tot["best_day_share"] < pay["consistency_pct"]
    )
    if not consistency_ok:
        # Extra profit needed so the best day drops under the consistency threshold.
        needed = round(tot["best_day"] / pay["consistency_pct"] - tot["cycle_total"], 2)
        missing.append(
            f"${needed:,.2f} more profit spread over other days: your best day is "
            f"{tot['best_day_share']*100:.0f}% of cycle profit (must be under "
            f"{pay['consistency_pct']*100:.0f}%)"
        )
    withdrawable = round(max(0.0, tot["total"] - lim.safety_net_profit), 2)
    eligible = not missing and withdrawable >= pay["min_payout_amount"]
    return {
        "eligible": eligible,
        "missing": missing,
        "qualifying_days": tot["qualifying_days"],
        "qualifying_days_needed": pay["min_qualifying_days"],
        "withdrawable_above_safety_net": withdrawable,
        "request_amount": min(withdrawable, lim.next_payout_cap) if eligible else 0.0,
        "next_payout_cap": lim.next_payout_cap,
        "payouts_taken": lim.payouts_taken,
        "max_payouts": lim.max_payouts,
        "consistency_ok": consistency_ok,
    }


def streak_exempt(cfg: dict, setup: str) -> bool:
    """Is this setup still allowed to trigger once the loss streak has closed the day?

    The streak lock exists to stop the same failing setup being taken again. A setup that
    only appears when the market brings it — the Fib pullback — is not that, so it stays
    eligible inside every other limit: the trade cap, the daily loss stop, the cooldown,
    the session window and the hard flat.
    """
    if not setup:
        return False
    exempt = cfg["my_rules"].get("loss_streak_exempt_setups", [])
    name = setup.strip().upper()
    return any(name.startswith(str(e).strip().upper()) for e in exempt)


def evaluate(cfg: dict, conn: sqlite3.Connection, when: datetime | None = None,
             setup: str = "") -> dict:
    """Full current state plus every blocking rule that is currently tripped.

    `setup` names the setup being staged, so a setup listed in `loss_streak_exempt_setups`
    can still be taken after the day's loss streak. Left empty, nothing is exempt.
    """
    r = cfg["my_rules"]
    pay = cfg["payout"]
    when = when or now_ct()
    acct = cfg["active_account"]
    taken = payouts_taken(conn, acct)
    lim = limits(cfg, payouts_taken=taken)
    st = day_state(conn, acct, trade_date(when))
    tot = account_totals(
        conn,
        acct,
        lim.min_daily_profit,
        since=last_payout_date(conn, acct),
        today=st.date,
    )

    loss_remaining = round(lim.max_daily_loss + min(st.realized, 0.0), 2)
    # The EOD threshold trails the highest end-of-day balance, so before any profit
    # it sits a full drawdown BELOW the starting balance (negative in P&L terms).
    eod_threshold = round(tot["eod_high"] - lim.eod_drawdown, 2)
    buffer_to_threshold = round(tot["total"] + st.realized - eod_threshold, 2)
    cap_today = day_cap(
        tot["prior_days_total"],
        tot["prior_best_day"],
        pay["consistency_pct"],
        floor=lim.daily_target,
    )
    pstat = payout_status(lim, tot, pay)

    blocks: list[str] = []
    warnings: list[str] = []

    if st.open_trade:
        blocks.append(
            f"Trade #{st.open_trade['id']} is still open — close and log it before staging another."
        )
    if st.realized <= -lim.max_daily_loss:
        blocks.append(
            f"YOUR DAILY STOP IS HIT (${st.realized:,.2f} vs -${lim.max_daily_loss:,.2f}). "
            f"Platform off. Apex would still let you lose ${lim.apex_daily_loss_limit:,.0f} today — "
            "that permission is what ends accounts. No 'one more to get it back'."
        )
    if r["lock_day_on_target_hit"] and st.realized >= lim.daily_target:
        blocks.append(
            f"TARGET HIT (${st.realized:,.2f} >= ${lim.daily_target:,.2f}) — this is a WIN, "
            f"and it counts as one of your {pay['min_qualifying_days']} qualifying days. "
            "Close the platform. Grinding past this is what cost you every previous account."
        )
    if len(st.trades) >= r["max_trades_per_day"]:
        blocks.append(f"Trade count cap reached ({r['max_trades_per_day']} for the day).")
    if st.consecutive_losses >= r["max_consecutive_losses_per_day"]:
        streak = (f"{st.consecutive_losses} consecutive losses — the market is not offering "
                  "your setup today.")
        if streak_exempt(cfg, setup):
            warnings.append(
                f"{streak} {setup.strip().upper()} is exempt from the streak lock — taken only "
                "if the market brings it, and only inside the trade cap, the daily loss stop "
                "and the cooldown."
            )
        else:
            blocks.append(streak)
    if st.last_loss_at is not None:
        cooldown_ends = st.last_loss_at + timedelta(minutes=r["cooldown_minutes_after_loss"])
        if when < cooldown_ends:
            mins = (cooldown_ends - when).total_seconds() / 60
            blocks.append(f"Cooldown after a loss: {mins:.0f} min remaining (revenge-trade guard).")
    t = when.timetz().replace(tzinfo=None)
    if not (_parse_ct(r["session_start_ct"]) <= t <= _parse_ct(r["session_end_ct"])):
        blocks.append(
            f"Outside your session window {ct_to_pt(r['session_start_ct'], when)}–"
            f"{ct_to_pt(r['session_end_ct'], when)} PT (now {pt(when)} PT)."
        )
    if st.realized > 0 and st.realized >= cap_today:
        blocks.append(
            f"CONSISTENCY CAP (${st.realized:,.2f} >= ${cap_today:,.2f}). One more dollar today "
            f"makes this day {pay['consistency_pct']*100:.0f}%+ of cycle profit and your payout "
            "button disappears until other days catch up. Stop."
        )
    if buffer_to_threshold <= lim.max_daily_loss:
        warnings.append(
            f"Only ${buffer_to_threshold:,.2f} above the EOD threshold — less than one full daily "
            "stop. Touching it is instant account failure. Half size or sit out."
        )
    if st.open_trade and t >= _parse_ct(r["hard_flat_time_ct"]):
        warnings.append(
            f"FLATTEN NOW — past {ct_to_pt(r['hard_flat_time_ct'], when)} PT with trade "
            f"#{st.open_trade['id']} open. "
            "Holding through the close forfeits the account and all balances."
        )
    if pstat["eligible"]:
        warnings.append(
            f"PAYOUT AVAILABLE: request ${pstat['request_amount']:,.2f} now. Take it. "
            "An unrequested payout is not money, it is exposure."
        )
    if lim.payouts_taken >= lim.max_payouts:
        warnings.append(
            f"All {lim.max_payouts} payouts taken — this PA closes. Requalify with a new evaluation."
        )

    return {
        "limits": lim.__dict__,
        "rules": r,
        "payout_rules": pay,
        "account_sizes": list(cfg["accounts"].keys()),
        "day": {
            "date": st.date,
            "realized": round(st.realized, 2),
            "trades": len(st.trades),
            "wins": st.wins,
            "losses": st.losses,
            "consecutive_losses": st.consecutive_losses,
            "loss_budget_remaining": max(0.0, loss_remaining),
            "target_progress": round(st.realized / lim.daily_target, 4) if lim.daily_target else 0,
            "qualifies": st.realized >= lim.min_daily_profit,
            "consistency_cap": cap_today,
            "open_trade": st.open_trade,
            "trade_list": st.trades,
        },
        "account": {
            **tot,
            "balance": round(lim.start_balance + tot["total"], 2),
            "profit_to_first_request": lim.profit_to_first_request,
            "target_progress": (
                round(tot["total"] / lim.profit_to_first_request, 4)
                if lim.profit_to_first_request
                else 0
            ),
            "safety_net_profit": lim.safety_net_profit,
            "eod_threshold": eod_threshold,
            "buffer_to_threshold": buffer_to_threshold,
        },
        "payout": pstat,
        "mae": {
            "enforced": cfg["mae"]["enforce"],
            "ceiling": mae_ceiling(cfg, round(tot["total"] - st.realized, 2), lim.eod_drawdown),
        },
        "blocks": blocks,
        "warnings": warnings,
        "can_trade": not blocks,
        "prohibitions": cfg["apex_prohibitions"],
    }


def size_trade(
    cfg: dict,
    side: str,
    entry: float,
    stop: float,
    target: float,
    mae_cap: float | None = None,
) -> dict:
    """Position sizing and per-trade validation. Size follows the stop, never the mood."""
    lim = limits(cfg)
    r = cfg["my_rules"]
    errors: list[str] = []

    side = side.lower()
    if side not in ("long", "short"):
        return {"ok": False, "errors": ["Side must be long or short."]}

    stop_points = (entry - stop) if side == "long" else (stop - entry)
    reward_points = (target - entry) if side == "long" else (entry - target)

    if stop_points <= 0:
        errors.append(f"Stop is on the wrong side of entry for a {side}.")
    elif stop_points > r["max_stop_points"]:
        errors.append(
            f"Stop is {stop_points:.2f} pts — wider than your {r['max_stop_points']} pt max. "
            "A stop this wide means you do not actually know where you are wrong."
        )
    elif stop_points < r["min_stop_points"]:
        errors.append(f"Stop is only {stop_points:.2f} pts — inside noise, you will be wicked out.")
    if reward_points <= 0:
        errors.append(f"Target is on the wrong side of entry for a {side}.")

    rr = (reward_points / stop_points) if stop_points > 0 else 0
    if stop_points > 0 and reward_points > 0 and rr < r["min_reward_to_risk"]:
        errors.append(
            f"Reward:risk is {rr:.2f}:1, below your {r['min_reward_to_risk']}:1 minimum. "
            "Skip it — Apex also prohibits disproportionate risk outright."
        )

    contracts = 0
    risk_dollars = reward_dollars = commission = 0.0
    if stop_points > 0:
        risk_per_contract = stop_points * lim.point_value
        contracts = min(int(lim.risk_per_trade // risk_per_contract), lim.max_contracts)
        if contracts < 1:
            errors.append(
                f"Even 1 contract risks ${risk_per_contract:,.2f}, above your "
                f"${lim.risk_per_trade:,.2f} per-trade cap. Tighten the stop or trade MES."
            )
            contracts = 0
        risk_dollars = round(contracts * risk_per_contract, 2)
        reward_dollars = round(contracts * reward_points * lim.point_value, 2)
        commission = round(contracts * lim.commission_round_trip, 2)
        heat = risk_dollars * r["max_mae_multiple_of_risk"]
        if mae_cap is not None and heat > mae_cap:
            errors.append(
                f"Open risk ${heat:,.2f} exceeds the MAE ceiling of ${mae_cap:,.2f}. Size down."
            )

    # Net of commissions, because Apex judges a qualifying day on NET profit.
    return {
        "ok": not errors,
        "errors": errors,
        "contracts": contracts,
        "stop_points": round(stop_points, 2),
        "reward_points": round(reward_points, 2),
        "reward_to_risk": round(rr, 2),
        "risk_dollars": risk_dollars,
        "reward_dollars": reward_dollars,
        "commission": commission if stop_points > 0 else 0.0,
        "net_if_target_hit": round(reward_dollars - commission, 2) if stop_points > 0 else 0.0,
        "net_if_stopped": round(-risk_dollars - commission, 2) if stop_points > 0 else 0.0,
        "makes_qualifying_day": (
            round(reward_dollars - commission, 2) >= lim.min_daily_profit
            if stop_points > 0
            else False
        ),
        "risk_cap": lim.risk_per_trade,
        "instrument": lim.instrument,
        "point_value": lim.point_value,
    }
