#!/usr/bin/env python3
"""Long-only daily-bar strategy comparison for the Robinhood agentic account.

Why this file exists, and why it looks nothing like paper_engine.py: the agentic account can
only place LONG equities and options orders, and under $25,000 the pattern-day-trader rule
allows 3 day trades per 5 business days. Both constraints push the same way — hold overnight
or for days, decide once a day, off the daily bar. That is a completely different animal from
the MES opening range, so it gets its own harness.

The honest reason for testing five ideas instead of building one: on the MES work I asserted a
flat 2R exit would beat Jonathan's hold-to-the-opposite-end rule and the data said the
opposite. Five candidates over 30 years means one will look good by luck, so the winner is
re-checked on years it never saw.

Costs modelled: no commission (Robinhood equities are free) but a spread/slippage haircut on
every fill, because a market order does not get the close.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SLIP_BPS = 2.0          # 0.02% each way: spread + slippage on a liquid ETF market order
ANNUAL_DAYS = 252


# ---------------------------------------------------------------------------- data
def load(symbol: str) -> pd.DataFrame:
    d = pd.read_csv(f"data/{symbol}_daily.csv", index_col=0)
    # Yahoo writes each row in the exchange's offset of that day, so EST and EDT rows mix and
    # pandas refuses to build a DatetimeIndex. Normalise to naive calendar dates.
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    # Dividends are most of the argument against a strategy that sits in cash 88% of the time,
    # so returns have to be total return. Yahoo's Close is split-adjusted only; scaling the whole
    # bar by Adj Close / Close makes every price dividend-adjusted and leaves the shapes intact.
    d = d[["Open", "High", "Low", "Close", "Adj Close", "Volume"]].dropna()
    ratio = d["Adj Close"] / d["Close"]
    for col in ("Open", "High", "Low", "Close"):
        d[col] = d[col] * ratio
    d["ret"] = d.Close.pct_change()
    d["sma200"] = d.Close.rolling(200).mean()
    d["sma50"] = d.Close.rolling(50).mean()
    d["hi50"] = d.High.rolling(50).max()
    d["rsi2"] = rsi(d.Close, 2)
    return d


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder's RSI. At n=2 this is the classic short-term exhaustion measure."""
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


# ---------------------------------------------------------------------------- results
@dataclass
class Result:
    name: str
    equity: pd.Series
    trades: list[dict] = field(default_factory=list)
    exposure: float = 0.0

    @property
    def years(self) -> float:
        return max((self.equity.index[-1] - self.equity.index[0]).days / 365.25, 1e-9)

    @property
    def cagr(self) -> float:
        return (self.equity.iloc[-1] / self.equity.iloc[0]) ** (1 / self.years) - 1

    @property
    def max_dd(self) -> float:
        return float((self.equity / self.equity.cummax() - 1).min())

    @property
    def sharpe(self) -> float:
        r = self.equity.pct_change().dropna()
        return float(r.mean() / r.std() * np.sqrt(ANNUAL_DAYS)) if r.std() else 0.0

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t["ret"] > 0) / len(self.trades)

    @property
    def worst_year(self) -> float:
        y = self.equity.resample("YE").last().pct_change().dropna()
        return float(y.min()) if len(y) else 0.0

    def row(self, budget: float) -> dict:
        return {
            "strategy": self.name,
            "CAGR %": round(self.cagr * 100, 2),
            "$ on {:.0f}/yr".format(budget): round(budget * self.cagr, 2),
            "max DD %": round(self.max_dd * 100, 1),
            "worst yr %": round(self.worst_year * 100, 1),
            "Sharpe": round(self.sharpe, 2),
            "trades": len(self.trades),
            "win %": round(self.win_rate * 100, 1),
            "time in mkt %": round(self.exposure * 100, 1),
        }


def run_positions(d: pd.DataFrame, pos: pd.Series, name: str,
                  entry_px: pd.Series | None = None,
                  exit_px: pd.Series | None = None) -> Result:
    """Turn a 0/1 position series into an equity curve, charging slippage on every change.

    pos is the position held THROUGH each bar's return, so it must already be shifted by the
    strategy: deciding on today's close and holding tomorrow means pos.shift(1).
    """
    pos = pos.fillna(0.0).clip(0, 1)
    gross = pos * d.ret.fillna(0.0)
    turns = pos.diff().abs().fillna(pos.iloc[0])
    cost = turns * (SLIP_BPS / 10_000)
    equity = (1 + gross - cost).cumprod()

    trades: list[dict] = []
    in_pos = False
    start_val = 1.0
    start_ts = None
    for ts, p in pos.items():
        if p > 0 and not in_pos:
            in_pos, start_val, start_ts = True, equity.loc[ts], ts
        elif p == 0 and in_pos:
            in_pos = False
            trades.append({"in": start_ts, "out": ts,
                           "ret": equity.loc[ts] / start_val - 1})
    if in_pos:
        trades.append({"in": start_ts, "out": pos.index[-1],
                       "ret": equity.iloc[-1] / start_val - 1})

    return Result(name=name, equity=equity, trades=trades, exposure=float(pos.mean()))


# ---------------------------------------------------------------------------- candidates
def buy_and_hold(d: pd.DataFrame) -> Result:
    """The benchmark that matters. Any strategy that cannot beat this is a worse idea than
    doing nothing, and doing nothing has no way to go wrong."""
    return run_positions(d, pd.Series(1.0, index=d.index), "buy and hold")


def dip_buy(d: pd.DataFrame, label: str = "dip buy (RSI2 + 200d)", **kw) -> Result:
    """Buy short-term exhaustion inside a long-term uptrend; exit on the bounce.

    The 200-day filter is the whole risk control: it keeps the strategy out of the market for
    the stretches when 'the dip' keeps dipping.
    """
    return run_positions(d, dip_positions(d, **kw), label)


def overnight(d: pd.DataFrame) -> Result:
    """Own the market only between the close and the next open.

    Documented drift, and it never holds through a session, so it is immune to intraday
    volatility. The catch is that it is a day trade's worth of exposure with a gap's worth of
    risk, and the gap is the one thing a stop cannot protect.
    """
    overnight_ret = d.Open / d.Close.shift(1) - 1
    cost = 2 * (SLIP_BPS / 10_000)          # in at the close, out at the open
    equity = (1 + overnight_ret.fillna(0) - cost).cumprod()
    trades = [{"in": ts, "out": ts, "ret": r}
              for ts, r in overnight_ret.dropna().items()]
    return Result("overnight hold (close to open)", equity, trades, exposure=0.0)


def breakout_50d(d: pd.DataFrame) -> Result:
    """Buy 50-day highs above the 200-day, exit when the 50-day average breaks.

    The equity-market cousin of Jonathan's opening range break: buy strength, hold the trend,
    give back some of it on the way out.
    """
    long = (d.Close >= d.hi50.shift(1)) & (d.Close > d.sma200)
    out = d.Close < d.sma50
    pos = np.zeros(len(d))
    for i in range(1, len(d)):
        if pos[i - 1] > 0:
            pos[i] = 0.0 if out.iloc[i] else 1.0
        else:
            pos[i] = 1.0 if long.iloc[i] else 0.0
    return run_positions(d, pd.Series(pos, index=d.index).shift(1), "50-day breakout")


def trend_filter(d: pd.DataFrame) -> Result:
    """Hold the index while it is above its 200-day average, sit in cash below it.

    One decision a month in practice, and the only candidate whose entire purpose is to miss
    the crashes rather than to catch the rallies.
    """
    pos = (d.Close > d.sma200).astype(float)
    return run_positions(d, pos.shift(1), "200-day trend filter")


def dip_positions(d: pd.DataFrame, rsi_in: float = 10, rsi_out: float = 65,
                  max_days: int = 10) -> pd.Series:
    """The dip-buy position series on its own, so other strategies can build on it."""
    pos = np.zeros(len(d))
    held = 0
    for i in range(1, len(d)):
        if pos[i - 1] > 0:
            held += 1
            pos[i] = 0.0 if (d.rsi2.iloc[i] >= rsi_out or held >= max_days) else 1.0
            held = 0 if pos[i] == 0 else held
        else:
            pos[i] = 1.0 if (d.Close.iloc[i] > d.sma200.iloc[i]
                             and d.rsi2.iloc[i] <= rsi_in) else 0.0
            held = 0 if pos[i] == 0 else 1
    return pd.Series(pos, index=d.index).shift(1)


def core_plus_dip(d: pd.DataFrame, core: float = 0.5) -> Result:
    """Hold a core position while above the 200-day, top up to full size on a dip.

    This is the only honest way to use the dip signal harder in this account: there is no
    margin borrowing, so 'size up' can never mean more than 100% of the cash. It means
    keeping less than 100% invested normally so there is room to add.
    """
    base = (d.Close > d.sma200).astype(float).shift(1) * core
    pos = np.maximum(base.fillna(0.0), dip_positions(d).fillna(0.0))
    return run_positions(d, pos, f"{core:.0%} core above 200d + full size on dips")


def synthetic_3x(d: pd.DataFrame, fee_annual: float = 0.0095 + 0.045) -> pd.DataFrame:
    """A 3x daily ETF built from the index, so the idea can be tested before TQQQ existed.

    Fee assumption: 0.95% expense ratio plus roughly 4.5% average financing on the 2x borrowed
    portion. Real TQQQ history is the check on whether this is close enough.
    """
    out = d.copy()
    out["ret"] = 3 * d.ret.fillna(0.0) - fee_annual / ANNUAL_DAYS
    out["Close"] = (1 + out.ret).cumprod()
    return out


def dip_buy_levered(signal: pd.DataFrame, traded: pd.DataFrame, label: str, **kw) -> Result:
    """Read the signal off the index, take the position in a leveraged ETF.

    This is the only leverage available here: the agentic account has no margin borrowing, but
    a 3x ETF is an ordinary long equity purchase. It is also the fastest way to turn a modest
    edge into a ruinous drawdown, which is exactly what the numbers have to be judged on.
    """
    pos = dip_positions(signal, **kw).reindex(traded.index).fillna(0.0)
    return run_positions(traded, pos, label)


def momentum_rotation(spy: pd.DataFrame, qqq: pd.DataFrame) -> Result:
    """Hold whichever of QQQ/SPY has the stronger 12-month return, cash if both are negative.

    Rebalanced monthly, so it is 12 decisions a year and no day trades ever.
    """
    px = pd.DataFrame({"SPY": spy.Close, "QQQ": qqq.Close}).dropna()
    mom = px.pct_change(ANNUAL_DAYS)
    month_end = px.resample("ME").last().index
    choice = pd.Series(index=px.index, dtype=object)
    for ts in month_end:
        window = mom.loc[:ts]
        if window.empty:
            continue
        last = window.iloc[-1]
        pick = last.idxmax() if last.max() > 0 else None
        choice.loc[ts:] = pick
    rets = px.pct_change()
    held = choice.shift(1)
    gross = pd.Series(
        [rets.loc[ts, h] if isinstance(h, str) else 0.0 for ts, h in held.items()],
        index=held.index).fillna(0.0)
    switch = (held != held.shift(1)) & held.notna()
    cost = switch.astype(float) * 2 * (SLIP_BPS / 10_000)
    equity = (1 + gross - cost).cumprod()
    trades = [{"in": ts, "out": ts, "ret": r} for ts, r in gross[held.notna()].items()]
    return Result("momentum rotation (SPY/QQQ, monthly)", equity, trades,
                  exposure=float(held.notna().mean()))


# ---------------------------------------------------------------------------- driver
def candidates(spy: pd.DataFrame, qqq: pd.DataFrame) -> list[Result]:
    return [
        buy_and_hold(spy),
        dip_buy(spy),
        dip_buy(qqq, "dip buy on QQQ"),
        dip_buy_levered(qqq, synthetic_3x(qqq), "dip buy, held in 3x QQQ (synthetic)"),
        core_plus_dip(spy, 0.5),
        overnight(spy),
        breakout_50d(spy),
        trend_filter(spy),
        momentum_rotation(spy, qqq),
    ]


def detail(r: Result) -> None:
    """The numbers that decide whether a curve is survivable, which a CAGR never shows:
    the worst single trade, how long a losing run gets, and the calendar years."""
    rets = [t["ret"] for t in r.trades]
    holds = [max((t["out"] - t["in"]).days, 1) for t in r.trades]
    streak = worst = 0
    for x in rets:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    yearly = r.equity.resample("YE").last().pct_change().dropna() * 100
    print(f"\n--- {r.name} ---")
    print(f"trades {len(rets)}, win rate {r.win_rate:.1%}, "
          f"average trade {np.mean(rets):+.2%}, best {max(rets):+.2%}, worst {min(rets):+.2%}")
    print(f"average hold {np.mean(holds):.1f} calendar days, longest {max(holds)}; "
          f"longest losing run {worst} trades")
    print(f"losing years: " + ", ".join(f"{ts.year} {v:+.1f}%"
                                       for ts, v in yearly.items() if v < 0))


def robustness(d: pd.DataFrame, sl: slice, label: str) -> pd.DataFrame:
    """A strategy that only works at one setting is a coincidence. Vary each knob and read the
    spread, not the best cell."""
    rows = []
    for rsi_in in (5, 10, 15, 20):
        for rsi_out in (50, 65, 80):
            for max_days in (5, 10, 20):
                r = dip_buy(d.loc[sl], rsi_in=rsi_in, rsi_out=rsi_out, max_days=max_days)
                rows.append({"buy RSI2 <=": rsi_in, "sell RSI2 >=": rsi_out,
                             "max days": max_days, "CAGR %": round(r.cagr * 100, 2),
                             "max DD %": round(r.max_dd * 100, 1),
                             "trades": len(r.trades),
                             "win %": round(r.win_rate * 100, 1)})
    out = pd.DataFrame(rows)
    print(f"\n=== {label}: dip-buy parameter grid ({len(out)} settings) ===")
    print(f"CAGR spread {out['CAGR %'].min():.2f}% to {out['CAGR %'].max():.2f}%, "
          f"median {out['CAGR %'].median():.2f}%, "
          f"{(out['CAGR %'] > 0).sum()}/{len(out)} settings profitable")
    return out


def table(results: list[Result], budget: float) -> pd.DataFrame:
    return pd.DataFrame([r.row(budget) for r in results])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=float, default=500.0)
    ap.add_argument("--split", default="2013-01-01",
                    help="in-sample ends / out-of-sample begins here")
    ap.add_argument("--detail", action="store_true",
                    help="per-trade and per-year breakdown of the leading candidates")
    ap.add_argument("--grid", action="store_true",
                    help="sweep the dip-buy parameters in both halves")
    args = ap.parse_args()

    spy, qqq = load("SPY"), load("QQQ")
    common = spy.index.intersection(qqq.index)

    print(f"SPY {spy.index[0].date()} → {spy.index[-1].date()}  ({len(spy)} sessions)")
    print(f"QQQ {qqq.index[0].date()} → {qqq.index[-1].date()}  ({len(qqq)} sessions)")
    print(f"Slippage charged: {SLIP_BPS} bps per side. No commission (Robinhood equities).")

    for label, sl in (("IN-SAMPLE (tune here)", slice(None, args.split)),
                      ("OUT-OF-SAMPLE (never touched)", slice(args.split, None))):
        s, q = spy.loc[sl], qqq.loc[sl]
        if len(s) < 300:
            continue
        print(f"\n=== {label}: {s.index[0].date()} → {s.index[-1].date()} ===")
        print(table(candidates(s, q), args.budget).to_string(index=False))

    print(f"\n=== FULL HISTORY (both ETFs available): "
          f"{common[0].date()} → {common[-1].date()} ===")
    print(table(candidates(spy.loc[common], qqq.loc[common]), args.budget)
          .to_string(index=False))

    # Does the synthetic 3x resemble the real thing? If not, none of its history means anything.
    tqqq = load("TQQQ")
    both = tqqq.index.intersection(qqq.index)
    synth = synthetic_3x(qqq).loc[both]
    real = tqqq.loc[both]
    print(f"\n=== Synthetic 3x QQQ vs real TQQQ, {both[0].date()} → {both[-1].date()} ===")
    print(f"daily return correlation {synth.ret.corr(real.ret):.4f}, "
          f"annualised drag of synthetic vs real "
          f"{(synth.ret.mean() - real.ret.mean()) * ANNUAL_DAYS * 100:+.2f}%")
    print(table([dip_buy_levered(qqq.loc[both], synth, "dip buy in synthetic 3x"),
                 dip_buy_levered(qqq.loc[both], real, "dip buy in real TQQQ"),
                 run_positions(real, pd.Series(1.0, index=real.index), "TQQQ buy and hold")],
                args.budget).to_string(index=False))

    if args.detail:
        for r in (dip_buy(qqq, "dip buy on QQQ, full history"),
                  dip_buy_levered(qqq, synthetic_3x(qqq), "dip buy in 3x QQQ, full history"),
                  buy_and_hold(spy)):
            detail(r)

    if args.grid:
        for label, sl in (("IN-SAMPLE", slice(None, args.split)),
                          ("OUT-OF-SAMPLE", slice(args.split, None))):
            g = robustness(spy, sl, label)
            print(g.sort_values("CAGR %", ascending=False).head(5).to_string(index=False))


if __name__ == "__main__":
    main()
