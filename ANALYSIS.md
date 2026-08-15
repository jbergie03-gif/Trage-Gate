# What your data actually says, and what I would do about it

Evidence base: 30 real MES sessions (19 Jun – 14 Aug 2026) exported from your own TradingView
Strategy Tester, 5-minute chart, opening range break, scale-out at 2R with a runner. Plus a
20-session Python pilot and a Monte Carlo over 4,000 simulated accounts per scenario. Every
number below is from those; where I am guessing, it says so.

## 1. The four findings that matter

**Your entire edge is three days.** Top 3 days: **+$1,479**. All 30 days: **+$1,091**. So the
other 27 sessions are **−$388** together. This is not a flaw — it is what an opening range
strategy IS. It pays on the few days the open actually trends and charges rent the rest of the
time. But it has two consequences you have to design around:

- **Missing a trend day costs more than taking a losing day.** Any rule that has you sitting
  out — a bad mood, a late start, a "I'll wait for confirmation today" — is far more expensive
  than a stop-out. This inverts normal discipline advice.
- **Cutting a winner short is the one unforgivable error.** Which is the strongest argument
  for exactly what you asked for: bank most of it at 2R, keep a runner on the trend days.

**Your losers were wrong, not unlucky.** Average maximum favourable excursion on the 16 losing
days: **$95** — under two-thirds of one R. Only **3 of 16** ever got a full R in profit before
dying, and losers died in an average of **29 minutes** while winners ran **105 minutes**.

That kills the most common instinct: widening the stop would not have saved them, it would only
have made them cost more. I tested it directly — a 2-point wider stop turns the pilot from
+$322 into **−$1,061**. The stop is not your problem. Trade *selection* is.

**Your exit is already efficient.** Winners captured **79%** of the best price they ever saw.
There is very little left on the table, so exit tinkering is close to a dead end. Stop
optimising it.

**Size is inverted against you.** The four days you traded 7–11 contracts lost **−$225**; the
14 days at 1–3 contracts made **+$783**. Cause: risk-based sizing hands you the most contracts
when the opening range is narrowest, and a narrow opening range is a chop day. You are largest
exactly when the setup is worst.

Caveat, and it is a big one: that is **four observations**. Suggestive, not proven.

## 2. The number nobody wants to look at

+$1,091 over 30 sessions is **+$36 per session**. Apex's first payout needs **+$3,600**.

At this expectancy that is **~100 trading sessions — about five months** — with no failed
account in between, and a **6-session losing streak already appeared** in a two-month sample.
The qualifying-days requirement is not the constraint (you had 8 in 30, you need 5). The
constraint is the profit total.

This is the honest reason 170 evaluations produced no payout, and it is arithmetic, not
psychology: **the expectancy has to roughly double before an EOD prop account is a realistic
vehicle.** Discipline gets you to survival. It does not get you to a payout on its own.

## 3. What I would change about your strategy

In priority order, most valuable first.

1. **Filter days, do not filter trades.** The edge is in trend days; the losses are chop. Every
   candidate filter must be tested on years of Pine data, not on these 30 days:
   - opening range width band (skip the narrowest days — the 2.5-point range day was your
     single worst, −$300)
   - the open's position relative to the prior day's range and the overnight range
   - whether the first break is *with* or *against* the overnight direction
2. **Cap contracts at 6 MES regardless of what the risk formula says.** This costs you nothing
   on the days that pay and directly attacks the inverted-size problem. It is also the honest
   response to a narrow range: less conviction, not more.
3. **Keep the 2R scale-out with the 25% runner.** Your data supports it: the runner produced
   **$451 of the $1,091** — 41% of the profit from about 10% of the size.
4. **Leave the stop alone.** Both the excursion data and the buffer test say so.
5. **Do not add the Fib trade yet.** Entry at the .618 with the stop at the full retracement is
   structurally **1.4:1** as traded — below your own 1.5:1 minimum — and on a 15-minute chart
   the retracement will usually be wider than your 12-point stop limit. Test it, in isolation,
   before it touches a live day.
6. **Add a kill switch on expectancy, not just on P&L.** If the rolling 20-trade expectancy is
   negative, stop trading the setup and go back to the tester. Losing money is normal; losing
   money while the expectancy has quietly turned is how accounts die.

## 4. What I would trade with my own money

Same setup, different priorities — capital preservation while the sample grows, then size.

- **One instrument (MES), one setup, one trade a day.** Your data shows one trade per day for
  30 straight sessions. That is the rarest and most valuable property in this whole project and
  I would not trade it away for more opportunities.
- **Fixed 3 contracts, not risk-normalised sizing**, until the day-filter is validated. Simple,
  and immune to the inverted-size trap.
- **Scale 75% at 2R, 25% runner trailing 1R from breakeven.** Unchanged — the evidence supports
  it and it matches how the P&L is actually distributed.
- **Two losses ends the day; no third trade.** Not for discipline theatre — because your losers
  cluster on chop days, and the second loss is the market telling you which kind of day it is.
- **I would not fund a prop account at +$36/session.** I would spend the next month running the
  Pine tester over years of MES data on the day-filters above, at zero cost, and only buy an
  evaluation once out-of-sample expectancy is roughly $75–100/session. That is the number that
  makes the payout math work.
- **And I would size up only after a payout, never before one.** Every account you have lost
  was lost on the way up, not on the way down.

## 5. What would change my mind

- If the day-filter work does not lift expectancy out-of-sample, the honest conclusion is that
  this is a break-even setup with good risk control, and no amount of discipline fixes that.
- If the 3-days-carry-everything shape does not hold over years, the runner is not worth
  keeping and a flat 2R is fine.
- 30 sessions is one market regime. None of this is proof.

## 6. What this is not

Not financial advice, and not a claim that the strategy is profitable. It is an honest reading
of a 30-session sample of simulated fills, and it can be wrong.
