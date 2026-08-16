# Long-only daily strategies for the Robinhood agentic account

Reproduce with `.venv/bin/python lab/equity_lab.py --budget 500 --detail --grid` from the repo
root. Raw output of the run this document describes is in `lab/run_output.txt`.

## Why these candidates and not the ORB

The agentic account can place **long equities and options orders only**, and below $25,000 the
pattern-day-trader rule allows three day trades per five business days. So the MES opening range
cannot be ported: it needs shorts and it needs day trades. Everything tested here is long-only,
decided on the daily close, and holds overnight or longer — which also removes the uptime problem,
since one decision a day near the close is all an agent has to be trusted with.

Costs: no commission (Robinhood equities are free), 2 bps of spread and slippage charged on every
fill because a market order does not get the closing print. Returns are **total return** —
dividends included, which matters enormously here and is discussed below.

Split: in-sample 1993–2012, out-of-sample 2013–2026. No parameter was chosen from the second half.

## Results

| strategy | CAGR in-sample | CAGR out-of-sample | max DD (full) | Sharpe (OOS) | trades | time in market |
|---|---|---|---|---|---|---|
| buy and hold SPY | 8.1% | **15.0%** | −55.2% | 0.92 | 1 | 100% |
| dip buy SPY (RSI2 ≤ 10, above 200d) | 6.2% | 3.8% | −14.8% | 0.64 | 205 | 12% |
| dip buy QQQ | 4.6% | 4.0% | −15.4% | 0.52 | 208 | 12% |
| dip buy QQQ, held in 3x (TQQQ) | 11.3% | 10.1% | −45.7% | 0.51 | 208 | 12% |
| **50% core above 200d + full size on dips** | 6.7% | 8.3% | **−16.4%** | **1.04** | 77 | 44% |
| 200-day trend filter | 6.0% | 11.7% | −28.6% | 1.01 | 95 | 75% |
| 50-day breakout | 2.9% | 3.4% | −23.8% | 0.45 | 72 | 44% |
| momentum rotation SPY/QQQ, monthly | 1.5% | 16.4% | −46.4% | 0.92 | 5399 | 78% |
| overnight hold, close to open | −0.1% | −1.1% | −72.0% | −0.05 | 6900 | 0% |

## What each result actually says

**Dividends decided this comparison, and they cut against the dip buy.** My first run used
unadjusted prices; correcting to total return moved buy-and-hold from 6.8% to 8.6% over the full
period and the 200-day trend filter from 4.7% to 6.6%, while barely moving the dip buy — because
a strategy that holds for six days at a time, 12% of the year, collects almost no dividends. Any
comparison of an in-and-out strategy against holding the index that ignores dividends is
flattering the in-and-out strategy by 1–2% a year. That single correction reversed my conclusion.

**No timing strategy here beat buy-and-hold on return.** Over the full 27 years buy-and-hold made
8.6%; the best alternative made 9.6% and that one (momentum rotation) is a mirage — see below.
What the good candidates beat it on is **drawdown**: −11% to −16% against −55%. That is the
honest trade being offered, and it is a real one, but it is not "more money".

**The overnight trade is a cost trap.** The close-to-open drift is real and documented, but
harvesting it takes 250 round trips a year. At 2 bps a side that is 2.8% of the account annually,
and it loses in both halves. This is the funded-account failure in a different costume: frequency
is what kills you, and it needs no psychological explanation.

**Momentum rotation is the trap I would have fallen into.** 1.5% for twenty years, then 16.4%.
That is not an edge appearing, it is QQQ beating SPY since 2013. Tested on recent data alone it
would have won, for the one reason with no predictive content. It also has a −42.5% year in it.

**The 50-day breakout is the closest cousin of your ORB, and it is the weakest real candidate.**
Buy strength, hold the trend, give some back on exit: 2.9% and 3.4%. Worth knowing before
assuming the MES logic transfers to equities — it does not appear to.

**The dip buy is the most statistically stable signal and the least useful on its own.** Across 36
combinations of entry RSI, exit RSI and maximum hold, **all 36 were profitable in both halves**
(in-sample median 4.4%, out-of-sample median 3.7%), and the best in-sample settings were also
near-best out-of-sample. That is what a genuine small edge looks like. But 4% a year unlevered is
below simply holding the index, so the signal only earns its place when it is used to *add* to a
position rather than to *be* the position.

## The version I would actually run

**50% core while above the 200-day, topped up to full size on a dip.** Out-of-sample 8.3% with a
−11% drawdown and a Sharpe of 1.04 — the best risk-adjusted result in the table, and it improved
from in-sample to out-of-sample rather than degrading. About **two trades a year**, six-day
top-ups, no day trades ever, and the dip signal is doing what it is actually good at.

For $500 that is roughly $41 a year. The point of the account at this size is not the $41 — it is
that the logic is simple enough to verify every step of, the worst case is around −$55, and it has
already survived thirteen years it was not fitted to.

## The 3x version, and the case against starting there

Signal off QQQ, position in TQQQ: **11.3% in-sample, 10.1% out-of-sample** — the most stable
absolute return in the table, and permitted in this account since a leveraged ETF is an ordinary
long equity purchase, not margin. Tested two ways because TQQQ only exists from 2010: a synthetic
3x built from QQQ returns (0.95% expense ratio plus ~4.5% financing on the borrowed portion)
tracks real TQQQ at **0.9989 daily correlation**, giving 9.86% against the real fund's 9.24% over
the overlap — so the pre-2010 history is usable and mildly optimistic.

Why I would still not start there:

- **Max drawdown −45.7%**, which on $500 is $229, and it is not a tail case. It lost money in
  **2007, 2008, 2011, 2016, 2018, 2020 and 2022**, with 2016 at −27.1% and 2018 at −22.5%. Two of
  those were unremarkable years for the index.
- **Worst single trade −23.5%**, and up to five losers in a row.
- **The 10% is leverage, not skill.** The signal makes 4%; the fund multiplies it. Leverage
  multiplies a wrong signal just as faithfully, and this signal is wrong 30% of the time.
- **It still did not beat buy-and-hold out-of-sample** (10.1% vs 15.0%).

A −45% drawdown in the first months of a real-money account is precisely the situation that ended
the funded accounts. That is the reason, not the arithmetic.

## Limits of this test

- Daily bars, so no intraday stop is modelled. A stop inside the holding window would change the
  drawdown figures and is untested here.
- One instrument at a time, no portfolio effects, no cash yield on the idle 50–88%. At current
  rates that idle cash is worth something real and is left out, which penalises the cash-heavy
  strategies.
- Nine strategies over one dataset. Even with the split, the winner carries some survivorship;
  the parameter grid matters more than any single line in the table.
- No claim of profitability. Nothing here has been traded, and historical bars are not evidence of
  future return.
