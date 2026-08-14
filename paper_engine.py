"""Paper trading engine — runs the setups mechanically and writes a session report.

This is a simulator. It does not connect to a broker, it cannot place an order, and it
never sees a credential. It reads price bars, applies the opening range break (and,
optionally, the Fib pullback) exactly as written, sizes every trade through the same rule
engine the dashboard uses, and fills against the bar data.

Two modes:

    live    poll a free 1-minute feed during the session and act on each closed bar
    replay  run a CSV of historical bars at speed, so a session takes seconds to watch

Paper trades go to their own journal (paper_journal.db) so they can never be confused
with real ones. At the end of each session it writes reports/session-YYYY-MM-DD.md:
what traded, what was skipped and why, which rule ended the day, whether the day
qualifies for Apex's $300 minimum, and the running progress to a payout.

    python paper_engine.py --replay es_1m.csv --speed 0
    python paper_engine.py --live
"""
from __future__ import annotations

import argparse
import json
import os
import time as time_mod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
os.environ.setdefault("TRADE_GATE_DB", str(BASE / "paper_journal.db"))

import rules  # noqa: E402  (must follow the env var so the paper DB is used)

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
STATE_FILE = BASE / "paper_state.json"
REPORT_DIR = BASE / "reports"


@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Position:
    side: str
    entry: float
    stop: float
    target: float
    contracts: int
    opened: datetime
    trade_id: int
    r_points: float
    setup: str = "orb"
    best: float = 0.0          # furthest favourable excursion, for the trailing exit
    trail: float = 0.0


@dataclass
class Session:
    """Everything that happened in one trading day, for the report."""
    date: str
    or_high: float | None = None
    or_low: float | None = None
    bars: int = 0
    trades: list[dict] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    ended_by: str = ""
    took_break: bool = False
    seen_blocks: set[str] = field(default_factory=set)
    # Fib leg state: pivots build an impulse leg, the pullback into it is the setup.
    bars_seen: list[Bar] = field(default_factory=list)
    leg_high: float | None = None
    leg_low: float | None = None
    leg_dir: int = 0            # 1 = up leg (buy the pullback), -1 = down leg
    leg_bar: int = 0
    fib_touched: bool = False

    def log(self, ts: datetime, msg: str) -> None:
        self.events.append(f"{ts.strftime('%H:%M')} {msg}")
        print(f"  {ts.strftime('%H:%M')}  {msg}", flush=True)


class PaperEngine:
    def __init__(self, cfg: dict, or_minutes: int, exit_rule: str, verbose: bool = True,
                 write_live: bool = False, setups: tuple[str, ...] = ("orb", "fib"),
                 pivot_len: int = 10, min_leg_pts: float = 6.0, leg_max_bars: int = 120):
        self.cfg = cfg
        self.or_minutes = or_minutes
        self.exit_rule = exit_rule
        self.setups = setups
        self.pivot_len = pivot_len
        self.min_leg_pts = min_leg_pts
        self.leg_max_bars = leg_max_bars
        self.verbose = verbose
        self.write_live = write_live
        self.pos: Position | None = None
        self.session: Session | None = None
        self.day_key: str | None = None
        self.completed: list[Session] = []

    # ---------------------------------------------------------------- helpers
    @property
    def r(self) -> dict:
        return self.cfg["my_rules"]

    def _mins_from_open(self, ts: datetime) -> int:
        h, m = (int(x) for x in self.r["session_start_ct"].split(":"))
        return (ts.hour * 60 + ts.minute) - (h * 60 + m)

    def _flat_deadline(self, ts: datetime) -> bool:
        h, m = (int(x) for x in self.r["hard_flat_time_ct"].split(":"))
        return (ts.hour * 60 + ts.minute) >= h * 60 + m

    def _entry_window(self, ts: datetime) -> bool:
        """Breaks are only taken inside the session, after the range is complete."""
        mins = self._mins_from_open(ts)
        end_h, end_m = (int(x) for x in self.r["session_end_ct"].split(":"))
        end = (end_h * 60 + end_m) - (int(self.r["session_start_ct"].split(":")[0]) * 60
                                      + int(self.r["session_start_ct"].split(":")[1]))
        return self.or_minutes <= mins <= end

    # ---------------------------------------------------------------- day roll
    def _roll_day(self, bar: Bar) -> None:
        key = rules.trade_date(bar.ts)
        if key == self.day_key:
            return
        if self.session is not None:
            self._close_session()
        self.day_key = key
        self.session = Session(date=key)
        if self.verbose:
            print(f"\n=== {key} ===", flush=True)

    def _close_session(self) -> None:
        if self.session is None:
            return
        s = self.session
        if not s.ended_by:
            if s.trades:
                s.ended_by = "the day's one opening range break was taken and closed"
            elif s.took_break:
                s.ended_by = "the opening break came and the rules refused it — no-trade day"
            else:
                s.ended_by = "no opening range break inside the session"
        self.completed.append(self.session)
        write_report(self.cfg, self.session)

    # ---------------------------------------------------------------- the loop
    def on_bar(self, bar: Bar) -> None:
        self._roll_day(bar)
        assert self.session is not None
        s = self.session
        s.bars += 1
        s.bars_seen.append(bar)
        mins = self._mins_from_open(bar.ts)
        if self.write_live:
            write_state(self.cfg, self, bar)

        if self.pos is not None:
            self._manage(bar)
            return

        # Build the opening range from the first N minutes of the session.
        if 0 <= mins < self.or_minutes:
            s.or_high = bar.high if s.or_high is None else max(s.or_high, bar.high)
            s.or_low = bar.low if s.or_low is None else min(s.or_low, bar.low)
            return

        if s.or_high is None or s.or_low is None or not self._entry_window(bar.ts):
            return

        # The opening range break is a trade about the opening bell: the FIRST break of the
        # range, once. A later re-break is a different setup on a stale level, not this one.
        if "orb" in self.setups and not s.took_break:
            side = None
            if bar.high >= s.or_high:
                side = "long"
            elif bar.low <= s.or_low:
                side = "short"
            if side is not None:
                s.took_break = True
                entry = s.or_high if side == "long" else s.or_low
                stop = s.or_low if side == "long" else s.or_high
                self._try_entry(bar, side, entry, stop, "ORB")
                return

        # The Fib pullback is the second setup of the day: it only gets looked at while
        # flat, and it shares the day's trade count and every lock with the ORB trade.
        if "fib" in self.setups and self.pos is None:
            self._check_fib(bar)

    # ------------------------------------------------------------------- fib
    def _pivot(self, bars: list[Bar], high_side: bool) -> float | None:
        """A pivot is only known pivot_len bars later — no looking into the future."""
        n = self.pivot_len
        if len(bars) < 2 * n + 1:
            return None
        window = bars[-(2 * n + 1):]
        mid = window[n]
        if high_side:
            return mid.high if all(b.high <= mid.high for b in window) else None
        return mid.low if all(b.low >= mid.low for b in window) else None

    def _check_fib(self, bar: Bar) -> None:
        s = self.session
        assert s is not None
        bars = s.bars_seen
        i = len(bars)

        # Pivots define the impulse leg, so "which leg" stops being a judgement call.
        pl = self._pivot(bars, high_side=False)
        ph = self._pivot(bars, high_side=True)
        if pl is not None:
            s.leg_low = pl
            if s.leg_high is not None and s.leg_high > pl + self.min_leg_pts:
                s.leg_dir, s.leg_bar, s.fib_touched = -1, i, False
        if ph is not None:
            s.leg_high = ph
            if s.leg_low is not None and ph > s.leg_low + self.min_leg_pts:
                s.leg_dir, s.leg_bar, s.fib_touched = 1, i, False

        if (s.leg_dir == 0 or s.leg_high is None or s.leg_low is None
                or i - s.leg_bar > self.leg_max_bars):
            return
        leg = s.leg_high - s.leg_low
        if leg < self.min_leg_pts:
            return

        near = s.leg_high - leg * 0.618 if s.leg_dir == 1 else s.leg_low + leg * 0.618
        if s.leg_dir == 1 and bar.low <= near:
            s.fib_touched = True
        elif s.leg_dir == -1 and bar.high >= near:
            s.fib_touched = True
        if not s.fib_touched:
            return

        # Take the bounce, not the knife: price has to close back out of the zone.
        if s.leg_dir == 1:
            if not (bar.close > near and bar.close > bar.open):
                return
            side, stop = "long", s.leg_low - 0.25
        else:
            if not (bar.close < near and bar.close < bar.open):
                return
            side, stop = "short", s.leg_high + 0.25

        # "Opposite end" for a pullback is the end of the leg it is retracing.
        leg_target = s.leg_high if side == "long" else s.leg_low
        s.leg_dir = 0        # one attempt per leg
        self._try_entry(bar, side, bar.close, stop, "FIB", target_override=leg_target)

    # ---------------------------------------------------------------- entries
    def _try_entry(self, bar: Bar, side: str, entry: float, stop: float, setup: str,
                   target_override: float | None = None) -> None:
        s = self.session
        assert s is not None
        r_pts = abs(entry - stop)
        lim = rules.limits(self.cfg)

        if self.exit_rule == "day_target":
            # Aim at exactly the job the day has to do: a qualifying day, net of fees.
            # A flat 2R can't do it — $150 of risk doubled is $300 gross, which is under
            # Apex's $300 NET minimum once commissions come out.
            per_contract = r_pts * lim.point_value
            n = min(int(lim.risk_per_trade // per_contract), lim.max_contracts) if per_contract else 0
            if n < 1:
                tgt_pts = r_pts * 2
            else:
                need = lim.daily_target + n * lim.commission_round_trip
                tgt_pts = need / (n * lim.point_value)
        else:
            tgt_pts = r_pts * (1.5 if self.exit_rule == "fixed_1.5R" else 2.0)
        target = entry + tgt_pts if side == "long" else entry - tgt_pts
        if target_override is not None and self.exit_rule == "opposite_end":
            target = target_override

        sizing = rules.size_trade(self.cfg, side, entry, stop, target)
        if not sizing["ok"]:
            reason = sizing["errors"][0]
            if reason not in s.skips:
                s.skips.append(f"{setup} {side}: {reason}")
                s.log(bar.ts, f"SKIP {setup} {side} — {reason}")
            return

        with rules.db() as conn:
            state = rules.evaluate(self.cfg, conn, when=bar.ts)
            if state["blocks"]:
                reason = state["blocks"][0]
                # Cooldown messages count down every minute; key on the rule, not the text.
                key = reason.split(":")[0].split("(")[0].strip()
                if key not in s.seen_blocks:
                    s.seen_blocks.add(key)
                    s.skips.append(reason)
                    s.log(bar.ts, f"BLOCKED — {reason}")
                if not s.ended_by and any(k in reason for k in
                                          ("TARGET HIT", "DAILY STOP", "Trade count",
                                           "consecutive losses", "CONSISTENCY")):
                    s.ended_by = reason
                return

            lim = rules.limits(self.cfg)
            cur = conn.execute(
                "INSERT INTO trades (staged_at, trade_date, account, instrument, side, entry, "
                "stop, target, contracts, risk_dollars, reward_dollars, setup, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bar.ts.isoformat(), s.date, lim.account, lim.instrument, side, entry, stop,
                 target, sizing["contracts"], sizing["risk_dollars"], sizing["reward_dollars"],
                 f"paper {setup} {self.or_minutes}m / {self.exit_rule}", "simulated"),
            )
            conn.commit()
            trade_id = cur.lastrowid

        self.pos = Position(side=side, entry=entry, stop=stop, target=target,
                            contracts=sizing["contracts"], opened=bar.ts, trade_id=trade_id,
                            r_points=r_pts, setup=setup, best=entry, trail=stop)
        aim = (f"target {target:.2f}" if self.exit_rule in
               ("fixed_2R", "fixed_1.5R", "day_target") else f"exit on {self.exit_rule}")
        s.log(bar.ts, f"ENTER {setup} {side.upper()} {sizing['contracts']} @ {entry:.2f}  "
                      f"stop {stop:.2f} ({r_pts:.2f} pts, ${sizing['risk_dollars']:,.0f})  {aim}")

    # ---------------------------------------------------------------- exits
    def _manage(self, bar: Bar) -> None:
        p = self.pos
        s = self.session
        assert p is not None and s is not None
        long = p.side == "long"

        # Pessimistic: if one bar covers both the stop and the target, assume the stop.
        hit_stop = bar.low <= p.trail if long else bar.high >= p.trail
        hit_target = bar.high >= p.target if long else bar.low <= p.target

        if hit_stop:
            self._exit(bar, p.trail, "stop")
            return
        target_rules = ("fixed_2R", "fixed_1.5R", "day_target")
        if (self.exit_rule in target_rules or p.setup == "FIB") and hit_target:
            self._exit(bar, p.target, "target")
            return

        if self.exit_rule == "trail_after_1R":
            p.best = max(p.best, bar.high) if long else min(p.best, bar.low)
            moved = (p.best - p.entry) if long else (p.entry - p.best)
            if moved >= p.r_points:
                new_trail = p.best - p.r_points if long else p.best + p.r_points
                p.trail = max(p.trail, new_trail) if long else min(p.trail, new_trail)

        if self._flat_deadline(bar.ts):
            self._exit(bar, bar.close, "hard flat time")
            return
        if self.exit_rule == "session_end" and not self._entry_window(bar.ts):
            self._exit(bar, bar.close, "session end")

    def _exit(self, bar: Bar, price: float, why: str) -> None:
        p = self.pos
        s = self.session
        assert p is not None and s is not None
        points = (price - p.entry) if p.side == "long" else (p.entry - price)
        inst = self.cfg["instruments"][self.cfg["instrument"]]
        gross = points * p.contracts * float(inst["point_value"])
        fees = p.contracts * float(inst["commission_round_trip"])
        pnl = round(gross - fees, 2)

        with rules.db() as conn:
            conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE id=?",
                         (price, pnl, bar.ts.isoformat(), p.trade_id))
            conn.commit()
            state = rules.evaluate(self.cfg, conn, when=bar.ts)

        s.trades.append({
            "opened": p.opened.strftime("%H:%M"), "closed": bar.ts.strftime("%H:%M"),
            "setup": p.setup,
            "side": p.side, "contracts": p.contracts, "entry": round(p.entry, 2),
            "stop": round(p.stop, 2), "exit": round(price, 2), "points": round(points, 2),
            "r": round(points / p.r_points, 2) if p.r_points else 0.0,
            "pnl": pnl, "why": why,
        })
        s.log(bar.ts, f"EXIT {why} @ {price:.2f}  {points:+.2f} pts  ${pnl:+,.2f}  "
                      f"(day ${state['day']['realized']:+,.2f})")
        self.pos = None

        for b in state["blocks"]:
            if any(k in b for k in ("TARGET HIT", "DAILY STOP", "Trade count",
                                    "consecutive losses", "CONSISTENCY")):
                if not s.ended_by:
                    s.ended_by = b
                    s.log(bar.ts, f"DAY OVER — {b.split('.')[0]}")
                break

        write_state(self.cfg, self, bar)

    def finish(self) -> None:
        self._close_session()
        if self.completed:
            write_summary(self.cfg, self.completed, self.or_minutes, self.exit_rule)


# -------------------------------------------------------------------- reporting
def write_state(cfg: dict, eng: PaperEngine, bar: Bar) -> None:
    """A small JSON snapshot so a live view can show what the engine is doing."""
    with rules.db() as conn:
        state = rules.evaluate(cfg, conn, when=bar.ts)
    s = eng.session
    STATE_FILE.write_text(json.dumps({
        "as_of": bar.ts.isoformat(),
        "last_price": bar.close,
        "session_date": s.date if s else None,
        "or_high": s.or_high if s else None,
        "or_low": s.or_low if s else None,
        "position": (None if eng.pos is None else {
            "side": eng.pos.side, "entry": eng.pos.entry, "stop": eng.pos.trail,
            "target": eng.pos.target, "contracts": eng.pos.contracts}),
        "day": state["day"],
        "account": state["account"],
        "payout": state["payout"],
        "blocks": state["blocks"],
        "events": (s.events[-12:] if s else []),
    }, indent=2, default=str))


def write_report(cfg: dict, s: Session) -> Path:
    """The end-of-session summary: what happened, and what it means for a payout."""
    REPORT_DIR.mkdir(exist_ok=True)
    with rules.db() as conn:
        state = rules.evaluate(cfg, conn, when=datetime.strptime(s.date, "%Y-%m-%d")
                               .replace(hour=10, tzinfo=CT))
        day = rules.day_state(conn, cfg["active_account"], s.date)
    lim = rules.limits(cfg)
    net = round(day.realized, 2)
    qualifies = net >= lim.min_daily_profit
    acct = state["account"]
    pay = state["payout"]

    lines = [
        f"# Paper session — {s.date}",
        "",
        f"**Net P&L ${net:,.2f}** · {len(s.trades)} trade(s) · "
        f"{'QUALIFYING DAY' if qualifies else 'does not qualify'} "
        f"(needs ${lim.min_daily_profit:,.0f} net)",
        "",
        f"- Opening range: {('%.2f' % s.or_high) if s.or_high else 'n/a'} / "
        f"{('%.2f' % s.or_low) if s.or_low else 'n/a'}"
        + (f"  ({s.or_high - s.or_low:.2f} pts)" if s.or_high and s.or_low else ""),
        f"- Day ended: {s.ended_by}",
        "- One opening range break per day: the first one. If the Fib pullback appears "
        "afterwards it is the second trade, under the same day limits.",
        f"- Target was ${lim.daily_target:,.0f}, loss stop was ${lim.max_daily_loss:,.0f}",
        "",
    ]

    if s.trades:
        lines += ["## Trades", "",
                  "| in | out | setup | side | qty | entry | stop | exit | pts | R | net $ | "
                  "exit reason |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for t in s.trades:
            lines.append(
                f"| {t['opened']} | {t['closed']} | {t.get('setup', 'ORB')} | {t['side']} | "
                f"{t['contracts']} | "
                f"{t['entry']:.2f} | {t['stop']:.2f} | {t['exit']:.2f} | {t['points']:+.2f} | "
                f"{t['r']:+.2f} | {t['pnl']:+,.2f} | {t['why']} |")
        lines.append("")
    else:
        lines += ["## Trades", "", "None. A day with no setup is a normal day, not a failure.", ""]

    if s.skips:
        lines += ["## Setups the rules refused", ""]
        lines += [f"- {x}" for x in s.skips]
        lines.append("")

    lines += [
        "## Where this leaves the account",
        "",
        f"- Balance ${acct['balance']:,.2f} · total P&L ${acct['total']:,.2f}",
        f"- Qualifying days: **{acct['qualifying_days']} of {cfg['payout']['min_qualifying_days']}** "
        f"(${lim.min_daily_profit:,.0f}+ net each)",
        f"- Profit to the first payout request: ${max(0.0, lim.profit_to_first_request - acct['total']):,.2f} "
        f"of ${lim.profit_to_first_request:,.2f}",
        f"- EOD threshold sits at a ${lim.start_balance + acct['eod_threshold']:,.2f} balance — "
        f"${acct['buffer_to_threshold']:,.2f} of room below you",
        "- Payout: " + (f"ELIGIBLE — request ${pay['request_amount']:,.2f}"
                        if pay["eligible"] else "still needs " + "; ".join(pay["missing"])),
        "",
        "_Simulated fills on delayed data. No broker, no orders, no automation — the engine "
        "only shows what the written rules would have done._",
    ]

    path = REPORT_DIR / f"session-{s.date}.md"
    path.write_text("\n".join(lines))
    print(f"\nreport → {path}", flush=True)
    return path


def write_summary(cfg: dict, sessions: list[Session], or_minutes: int, exit_rule: str) -> Path:
    """One file covering every session run, so the days stack into a record."""
    REPORT_DIR.mkdir(exist_ok=True)
    lim = rules.limits(cfg)
    with rules.db() as conn:
        state = rules.evaluate(cfg, conn)
    days = [(s, sum(t["pnl"] for t in s.trades)) for s in sessions]
    traded = [d for d in days if d[0].trades]
    wins = [t for s, _ in days for t in s.trades if t["pnl"] > 0]
    losses = [t for s, _ in days for t in s.trades if t["pnl"] <= 0]
    total = round(sum(p for _, p in days), 2)
    green = [p for _, p in traded if p > 0]
    qual = [p for _, p in days if p >= lim.min_daily_profit]
    worst = min((p for _, p in days), default=0.0)
    by_setup: dict[str, list[dict]] = {}
    for s, _ in days:
        for t in s.trades:
            by_setup.setdefault(t.get("setup", "ORB"), []).append(t)

    lines = [
        f"# Paper run summary — {len(days)} sessions",
        "",
        f"Setup: {or_minutes}-minute opening range, exit `{exit_rule}`, "
        f"{lim.account} {lim.instrument}, ${lim.risk_per_trade:,.0f} risk per trade.",
        "",
        "| setup | trades | net $ | wins |",
        "|---|---|---|---|",
    ] + [
        f"| {name} | {len(ts)} | {sum(t['pnl'] for t in ts):+,.2f} | "
        f"{len([t for t in ts if t['pnl'] > 0])} |"
        for name, ts in by_setup.items()
    ] + [
        "",
        f"- **Net P&L ${total:,.2f}** across {len(wins) + len(losses)} trades "
        f"({len(wins)}W / {len(losses)}L)",
        f"- Days traded: {len(traded)} of {len(days)} — the rest had no setup the rules would take",
        f"- Green days {len(green)} of {len(traded)}; worst day ${worst:,.2f} "
        f"(limit ${lim.max_daily_loss:,.0f})",
        f"- **Qualifying days ({lim.min_daily_profit:,.0f}+ net): {len(qual)}** — "
        f"{cfg['payout']['min_qualifying_days']} are needed for a payout",
        f"- Account P&L now ${state['account']['total']:,.2f} of the "
        f"${lim.profit_to_first_request:,.0f} a first request needs",
        "",
        "| date | trades | net $ | qualifying | how the day ended |",
        "|---|---|---|---|---|",
    ]
    for s, p in days:
        lines.append(f"| {s.date} | {len(s.trades)} | {p:+,.2f} | "
                     f"{'yes' if p >= lim.min_daily_profit else '—'} | "
                     f"{s.ended_by.split('.')[0][:60]} |")
    lines += [
        "",
        "Sample-size warning: this is a few weeks of one market regime on delayed data with "
        "simulated fills. It shows the rules working, not that the setup has an edge. Years of "
        "history in the Strategy Tester decide that.",
    ]
    path = REPORT_DIR / "summary.md"
    path.write_text("\n".join(lines))
    print(f"summary → {path}", flush=True)
    return path


# -------------------------------------------------------------------- feeds
def replay_bars(csv_path: str):
    import pandas as pd
    df = pd.read_csv(csv_path)
    # yfinance exports carry a second header row of ticker names; drop it.
    if str(df.iloc[0, 0]).strip().lower() in ("ticker", "symbol"):
        df = pd.read_csv(csv_path, skiprows=[1])
    names = ("datetime", "date", "time", "timestamp", "index", "price", "unnamed: 0")
    tcol = next((c for c in df.columns if str(c).strip().lower() in names), df.columns[0])
    for c in df.columns:
        if c != tcol:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[c for c in df.columns if str(c).lower() in
                           ("open", "high", "low", "close")])
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    df = df.sort_values(tcol)
    cols = {c.lower(): c for c in df.columns}
    for _, row in df.iterrows():
        ts = row[tcol].tz_convert(CT).to_pydatetime()
        yield Bar(ts, float(row[cols["open"]]), float(row[cols["high"]]),
                  float(row[cols["low"]]), float(row[cols["close"]]))


def today_bars(symbol: str):
    """Every 1-minute bar of the most recent session, for a post-close run."""
    import yfinance as yf
    df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=False)
    if df is None or not len(df):
        return
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    for ts, row in df.iterrows():
        yield Bar(ts.tz_convert(CT).to_pydatetime(), float(row["Open"]), float(row["High"]),
                  float(row["Low"]), float(row["Close"]))


def live_bars(symbol: str, poll_seconds: int = 30):
    """Free delayed 1-minute bars. Yields each bar once, after it closes."""
    import yfinance as yf
    seen: set[datetime] = set()
    while True:
        try:
            df = yf.download(symbol, period="1d", interval="1m",
                             progress=False, auto_adjust=False)
            if df is not None and len(df):
                if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                    df.columns = df.columns.get_level_values(0)
                for ts, row in df.iloc[:-1].iterrows():   # the last bar is still forming
                    t = ts.tz_convert(CT).to_pydatetime()
                    if t in seen:
                        continue
                    seen.add(t)
                    yield Bar(t, float(row["Open"]), float(row["High"]),
                              float(row["Low"]), float(row["Close"]))
        except Exception as exc:      # a feed hiccup must not kill the session
            print(f"feed error: {exc}", flush=True)
        time_mod.sleep(poll_seconds)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", metavar="CSV", help="replay historical bars from a CSV")
    ap.add_argument("--live", action="store_true", help="poll a free delayed 1-minute feed")
    ap.add_argument("--today", action="store_true",
                    help="pull today's 1-minute bars once, run them, write the report and exit")
    ap.add_argument("--symbol", default="ES=F")
    ap.add_argument("--speed", type=float, default=0.0,
                    help="seconds to pause per bar in replay (0 = as fast as possible)")
    ap.add_argument("--or-minutes", type=int, default=2)
    ap.add_argument("--exit", dest="exit_rule", default="opposite_end",
                    choices=["opposite_end", "fixed_2R", "fixed_1.5R",
                             "trail_after_1R", "session_end", "day_target"],
                    help="day_target sizes the target to finish a qualifying day in one trade")
    ap.add_argument("--setups", default="orb,fib",
                    help="which setups to run: orb, fib, or both (default both)")
    ap.add_argument("--pivot-len", type=int, default=10,
                    help="bars each side of a Fib pivot — this one number moves everything")
    ap.add_argument("--min-leg", type=float, default=6.0, help="minimum Fib leg (points)")
    ap.add_argument("--reset", action="store_true", help="wipe the paper journal first")
    ap.add_argument("--live-view", action="store_true",
                    help="update paper_state.json every bar so /paper can be watched")
    args = ap.parse_args()

    if args.reset and Path(os.environ["TRADE_GATE_DB"]).exists():
        Path(os.environ["TRADE_GATE_DB"]).unlink()

    cfg = rules.load_config()
    setups = tuple(s.strip().lower() for s in args.setups.split(",") if s.strip())
    eng = PaperEngine(cfg, args.or_minutes, args.exit_rule,
                      write_live=bool(args.live or args.live_view),
                      setups=setups, pivot_len=args.pivot_len, min_leg_pts=args.min_leg)
    lim = rules.limits(cfg)
    print(f"Paper engine · {lim.account} {lim.instrument} · {args.or_minutes}-min opening range "
          f"· exit {args.exit_rule}\nRisk ${lim.risk_per_trade:,.0f}/trade · target "
          f"${lim.daily_target:,.0f} · day stop ${lim.max_daily_loss:,.0f}\n"
          f"Journal: {os.environ['TRADE_GATE_DB']} (simulated — never the real one)")

    if args.replay:
        for bar in replay_bars(args.replay):
            eng.on_bar(bar)
            if args.speed:
                time_mod.sleep(args.speed)
        eng.finish()
    elif args.today:
        # One post-close pass over the day: same rules, no waiting around.
        n = 0
        for bar in today_bars(args.symbol):
            eng.on_bar(bar)
            n += 1
        if not n:
            print("No bars for today — market holiday, or the free feed is empty.", flush=True)
        eng.finish()
    elif args.live:
        print("Waiting for bars. Ctrl-C to stop.", flush=True)
        try:
            for bar in live_bars(args.symbol):
                eng.on_bar(bar)
        except KeyboardInterrupt:
            eng.finish()
    else:
        ap.error("choose --replay CSV or --live")


if __name__ == "__main__":
    main()
