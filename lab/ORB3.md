# The 3-minute opening candle: does width predict the break?

Jonathan's rule, as he wrote it: the 06:30–06:32 PT candle is the base of the trade, the first
candle to break either end takes the trade in that direction, the stop is the opposite end of
that candle, and the target is 1.5R while we test it.

Two questions came out of 2026-08-18, when the opening candle was 15.75 points wide — wider than
the 12-point maximum stop in `my_rules`:

1. Should a candle wider than the cap be traded with a 12-point stop, or skipped?
2. Jonathan's read was that wide opening candles rarely break out, so those days should be
   skipped entirely. Is that true?

## Sample

Every session of 1-minute ES the free feed still serves: **21 sessions, 2026-07-21 → 2026-08-18**
(`data/ES_1min_recent.csv`, refreshed with `python lab/orb3_study.py --fetch`). Fills are
simulated from 1-minute OHLC; a bar covering both the stop and the target is scored as the stop.
Sizing is the live one — $150 of risk, MES at $5/point, commissions out.

Median candle: **13.00 points**. Sixty-two percent of sessions (13 of 21) open wider than the
12-point cap, so this is not an edge case — it is most days.

## Answer to question 2: the hypothesis is not supported

| opening candle | sessions | broke the candle | stopped out | hit 1.5R | net (12-pt cap) |
|---|---|---|---|---|---|
| > 12 pts | 13 | 13 / 13 (100%) | 6 (46%) | 6 (46%) | **+$405.26** |
| <= 12 pts | 8 | 8 / 8 (100%) | 6 (75%) | 2 (25%) | **-$351.03** |

Every session in the sample broke its opening candle inside the entry window — all 21, wide and
narrow alike. There is no "wide days don't break out" effect here to skip; a 3-minute candle is
small enough that price leaves it every day.

If anything the sample points the other way: the wide-candle days were the ones that followed
through (46% stopped out vs 75%, median best excursion 1.35R vs 0.54R). That is the opposite of
the hypothesis, and it is also **13 days against 8** — far too few to trust. Treat it as "no
evidence for skipping wide days", not as "wide days are the good ones".

## Answer to question 1: cap the stop, don't widen it

Same 13 wide-candle sessions, only the stop placement changes:

| stop on wide-candle days | stopped out | hit 1.5R | net |
|---|---|---|---|
| clamped to 12 pts | 6 (46%) | 6 (46%) | +$405.26 |
| the full opposite end | 8 (62%) | 4 (31%) | -$158.53 |

The clamp wins for a mechanical reason, not a market one: a 1.5R target measured off a 20-point
stop is 30 points away and the day rarely travels that far, while 1.5R off a 12-point stop is 18
points and reachable. The wider stop also sizes the position down until one contract's win cannot
pay for the day. 2026-08-12 is the clearest case — a 21.25-point candle, still open at the
12:55 flat time, +$75 with the clamp.

So: on a wide-candle day, enter at the candle's edge and put the stop 12 points behind the entry,
inside the candle. `paper_engine.py --cap-orb-stop` does this.

## What this does not say

Twenty-one sessions of one summer regime on a delayed retail feed, with fills invented from
1-minute bars. Both buckets are single digits to low teens; a 46% vs 75% stop-out rate on 13 and 8
trades is well inside noise. Nothing here says the setup makes money — the whole 21-session ORB
line is +$54 net, which is zero. It says the stop cap is the better of two stop placements, and
that the wide-day skip Jonathan suspected is not in the data.
