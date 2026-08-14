"""Monte Carlo test of the rules themselves.

This does not test a trading edge, because there isn't one yet — it takes an edge as an
assumption (win rate and reward:risk) and asks a different question: given the SAME edge,
how often does each behaviour pattern reach a payout before it destroys the account?

Every account parameter and every rule comes from config.json via rules.py, so this
simulates the actual gate, not a paraphrase of it.

    .venv/bin/python simulate.py
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

import rules

TRADING_DAYS = 250  # about a year of sessions
RUNS = 4000
SEED = 20260814


@dataclass
class Policy:
    """How a trader behaves. The only differences between runs that matter."""
    name: str
    blurb: str
    max_trades_per_day: int
    stop_at_target: bool           # quit the day once the profit target is hit
    daily_loss_stop: bool          # honour a personal daily loss limit
    max_consecutive_losses: int    # 0 = no limit
    risk_multiple_after_loss: float = 1.0   # 2.0 = double down to win it back
    risk_multiple_of_cap: float = 1.0       # 1.0 = risk exactly the per-trade cap
    target_multiple: float = 1.0            # >1 = hold for a bigger day than planned
    setup_decay: float = 0.03               # win rate lost per extra trade taken in a day
    tilt_penalty: float = 0.0               # win rate lost on a trade taken right after a loss


@dataclass
class Result:
    paid: bool = False
    failed: bool = False
    days_to_first_payout: int | None = None
    payouts: list = field(default_factory=list)
    days_survived: int = 0
    peak: float = 0.0

    @property
    def total_paid(self):
        return sum(self.payouts)


STOP_POINTS = 6.0  # a typical stop inside the 2-12 point rule; sets $ risk per contract


def win_prob(skill: float, rr: float, trade_index: int, pol: Policy, after_loss: bool) -> float:
    """Probability this particular trade wins.

    Three effects the rules exist to contain, and which a naive simulation misses:

    1. A wider target is hit less often. For a driftless price path with a stop at -1R and
       a target at +kR, P(win) = 1/(1+k). `skill` is the edge on top of that baseline, so
       holding for a bigger day lowers the hit rate instead of multiplying the profit.
    2. Later trades in a day are worse trades. The first is the setup you waited for; the
       fifth is one you talked yourself into.
    3. Trading immediately after a loss is worse than trading flat.
    """
    p = 1.0 / (1.0 + rr * pol.target_multiple) + skill
    p -= pol.setup_decay * max(0, trade_index - 1)
    if after_loss:
        p -= pol.tilt_penalty
    return min(0.95, max(0.02, p))


def run_account(pol: Policy, lim, pay_rules, schedule: list, win_rate: float, rr: float,
                rng: random.Random, days: int = TRADING_DAYS) -> Result:
    """One simulated account life, trade by trade, under one behaviour policy.

    `win_rate` is the hit rate on the planned setup at the planned target. The edge that
    implies is carried across to whatever other trades the policy chooses to take.
    """
    res = Result()
    skill = win_rate - 1.0 / (1.0 + rr)   # edge above a no-skill random walk
    pnl = 0.0            # cumulative net P&L against the starting balance
    eod_high = 0.0       # highest closing P&L, which is what the EOD drawdown trails
    day_pnls: list[float] = []      # every completed day, for the qualifying-day count
    cycle_start = 0                  # index into day_pnls where the payout cycle began
    fee_per_contract = lim.commission_round_trip
    per_contract = STOP_POINTS * lim.point_value

    for day in range(1, days + 1):
        # Threshold is set by the previous close and enforced during this session.
        threshold = eod_high - lim.eod_drawdown
        day_pnl = 0.0
        consec_losses = 0
        last_was_loss = False

        for i in range(1, pol.max_trades_per_day + 1):
            if pol.stop_at_target and day_pnl >= lim.daily_target:
                break
            if pol.daily_loss_stop and day_pnl <= -lim.max_daily_loss:
                break
            if pol.max_consecutive_losses and consec_losses >= pol.max_consecutive_losses:
                break

            risk = lim.risk_per_trade * pol.risk_multiple_of_cap
            if last_was_loss:
                risk *= pol.risk_multiple_after_loss
            # Apex's own contract limit is the ceiling no policy can exceed.
            contracts = max(1, min(lim.max_contracts, round(risk / per_contract)))
            risk = contracts * per_contract
            fees = contracts * fee_per_contract

            if rng.random() < win_prob(skill, rr, i, pol, last_was_loss):
                day_pnl += risk * rr * pol.target_multiple - fees
                consec_losses = 0
                last_was_loss = False
            else:
                day_pnl -= risk + fees
                consec_losses += 1
                last_was_loss = True

            # A threshold breach ends the account the moment it happens.
            if pnl + day_pnl <= threshold:
                res.failed = True
                res.days_survived = day
                return res

        pnl += day_pnl
        day_pnls.append(day_pnl)
        eod_high = max(eod_high, pnl)
        res.peak = max(res.peak, pnl)

        if pnl <= threshold:
            res.failed = True
            res.days_survived = day
            return res

        # --- payout eligibility, exactly as the app computes it ---
        cycle = day_pnls[cycle_start:]
        qualifying = sum(1 for d in cycle if d >= lim.min_daily_profit)
        cycle_total = sum(cycle)
        best = max([d for d in cycle if d > 0], default=0.0)
        consistent = cycle_total <= 0 or best / cycle_total < pay_rules["consistency_pct"]
        withdrawable = pnl - lim.safety_net_profit

        if (qualifying >= pay_rules["min_qualifying_days"]
                and pnl >= lim.profit_to_first_request
                and consistent
                and withdrawable >= pay_rules["min_payout_amount"]):
            cap = schedule[min(len(res.payouts), len(schedule) - 1)]
            amount = min(withdrawable, cap)
            res.payouts.append(amount)
            if res.days_to_first_payout is None:
                res.days_to_first_payout = day
                res.paid = True
            pnl -= amount              # the money leaves the account
            eod_high = min(eod_high, pnl)   # and the threshold follows it down
            cycle_start = len(day_pnls)     # consistency measures from the last payout
            if len(res.payouts) >= pay_rules["max_payouts"]:
                res.days_survived = day
                return res

    res.days_survived = days
    return res


def summarize(name, results, days=TRADING_DAYS):
    n = len(results)
    paid = [r for r in results if r.paid]
    failed = [r for r in results if r.failed]
    d = [r.days_to_first_payout for r in paid]
    return {
        "policy": name,
        "paid_pct": 100.0 * len(paid) / n,
        "failed_pct": 100.0 * len(failed) / n,
        "median_days_to_payout": statistics.median(d) if d else None,
        "avg_payouts": statistics.mean(len(r.payouts) for r in results),
        "avg_paid": statistics.mean(r.total_paid for r in results),
        "median_survival": statistics.median(r.days_survived for r in results),
    }


def policies():
    return [
        Policy("The gate (my rules)",
               "3 trades, day locks at target, -$450 stop, 2 consecutive losses ends the day",
               max_trades_per_day=3, stop_at_target=True, daily_loss_stop=True,
               max_consecutive_losses=2, tilt_penalty=0.05),
        Policy("No target lock",
               "identical, except a green day is allowed to keep going",
               max_trades_per_day=3, stop_at_target=False, daily_loss_stop=True,
               max_consecutive_losses=2, tilt_penalty=0.05),
        Policy("Hold for a bigger day",
               "targets held for 2x — the 'today is the day' pattern",
               max_trades_per_day=3, stop_at_target=False, daily_loss_stop=True,
               max_consecutive_losses=2, target_multiple=2.0, tilt_penalty=0.05),
        Policy("Revenge sizing",
               "doubles risk after a loss, and tilts while doing it",
               max_trades_per_day=3, stop_at_target=True, daily_loss_stop=True,
               max_consecutive_losses=0, risk_multiple_after_loss=2.0, tilt_penalty=0.10),
        Policy("Overtrading",
               "10 trades a day, no daily stop, no target lock",
               max_trades_per_day=10, stop_at_target=False, daily_loss_stop=False,
               max_consecutive_losses=0, tilt_penalty=0.05),
        Policy("What broke the last accounts",
               "green day extended, 2x targets, 2x risk after a loss, 8 trades, no daily stop",
               max_trades_per_day=8, stop_at_target=False, daily_loss_stop=False,
               max_consecutive_losses=0, risk_multiple_after_loss=2.0, target_multiple=2.0,
               risk_multiple_of_cap=2.0, tilt_penalty=0.10),
    ]


def main():
    cfg = rules.load_config()
    cfg["active_account"] = "100K"
    cfg["instrument"] = "MES"
    lim = rules.limits(cfg)
    pay = cfg["payout"]
    schedule = cfg["accounts"][cfg["active_account"]]["max_payouts_schedule"]

    print(f"Monte Carlo — {cfg['active_account']} EOD, {RUNS:,} accounts each, "
          f"{TRADING_DAYS} sessions\n"
          f"risk {lim.risk_per_trade:,.0f}/trade · target {lim.daily_target:,.0f} · "
          f"stop {lim.max_daily_loss:,.0f} · drawdown {lim.eod_drawdown:,.0f} · "
          f"first payout needs +{lim.profit_to_first_request:,.0f}")

    scenarios = [
        (0.45, 2.5, "a real edge"),
        (0.40, 2.0, "a modest edge"),
        (0.3333, 2.0, "no edge at all — a coin flip after fees"),
        (0.30, 2.0, "slightly negative — the most likely truth of a trader who never got paid"),
    ]
    for win_rate, rr, label in scenarios:
        edge = win_rate * rr - (1 - win_rate)
        print(f"\n=== win rate {win_rate:.0%} at {rr}:1 — {label}\n"
              f"    (expectancy {edge:+.2f}R per planned trade) ===")
        print(f"{'behaviour':<32}{'paid':>7}{'failed':>8}{'med days':>10}"
              f"{'payouts':>9}{'avg $ paid':>12}")
        for pol in policies():
            rng = random.Random(SEED)
            out = [run_account(pol, lim, pay, schedule, win_rate, rr, rng) for _ in range(RUNS)]
            s = summarize(pol.name, out)
            md = f"{s['median_days_to_payout']:.0f}" if s["median_days_to_payout"] else "—"
            print(f"{pol.name:<32}{s['paid_pct']:>6.1f}%{s['failed_pct']:>7.1f}%{md:>10}"
                  f"{s['avg_payouts']:>9.2f}{s['avg_paid']:>12,.0f}")

    print("\nHow to read this")
    print("- 'paid' is the share of accounts that reached at least one approved payout;")
    print("  'failed' is the share that touched the EOD threshold and died.")
    print("- Every row in a block has the SAME skill. Only the behaviour changes.")
    print("- Wider targets are modelled as harder to hit (P(win) falls as the target grows),")
    print("  later trades in a day as worse setups, and post-loss trades as worse again.")
    print("  Without those three effects a simulation says overtrading is free money.")
    print("- The rules cost speed when the edge is real and save the account when it is not.")
    print("  Since you have never been paid, plan for the bottom two blocks, not the top.")


if __name__ == "__main__":
    main()
