# Does the second ORB trade in the same direction pay?

Question: the first opening-range break fails often — what happens if you take the second break in
the same direction after it stops out?

Answered twice. First on the 21 sessions the free Yahoo feed serves, where the numbers moved 20
points whenever an assumption moved and nothing could be concluded. Then on **152 complete
sessions, 2024-08 → 2026-08**, pulled with `lab/deep_history.py` from Dukascopy's open tick
archive. That is the sample below, and it is large enough to say something.

Rules held constant: stop at the opposite end of the opening range clamped to 12 points, ~$150 of
risk, commissions in, the engine's 15-minute post-loss cooldown applied before the re-entry, a bar
covering both stop and target scored as the stop.

    close   trigger: a bar closes back through the broken level   (what --orb-reentry does today)
    touch   trigger: price simply trades back through the level

## The first trade fails at least half the time

| Opening range | Target | Stopped out | Hit target | First-trade net | Per trade |
|---|---|---|---|---|---|
| 3-min | 1.0R | 76/152 (50%) | 76 (50%) | −$528 | −$3.48 |
| 3-min | 1.5R | 91/152 (60%) | 61 (40%) | −$554 | −$3.65 |
| 3-min | 2.0R | 96/152 (63%) | 56 (37%) | +$1,445 | +$9.51 |
| 2-min | 1.5R | 95/152 (62%) | 57 (38%) | −$1,780 | −$11.71 |
| 2-min | 2.0R | 102/152 (67%) | 50 (33%) | −$845 | −$5.56 |

Jonathan's read is right — and the more important finding is in the last two columns. **Every one of
those win rates is what a coin flip pays at that target**: 50% at 1R, 40% at 1.5R, 34% at 2R. The
opening-range break in this sample is a breakeven bet before commissions and a slow bleed after
them. That is the thing worth fixing; the second trade is a detail next to it.

## The re-entry: the direct answer

| Range | Target | Triggered on stop-out days | Win rate | Net | Per re-entry |
|---|---|---|---|---|---|
| 3-min | 1.0R | close 46/76 · touch 52/76 | **61%** · **60%** | +$1,075 · +$1,072 | +$23 · +$21 |
| 3-min | 1.5R | close 54/91 · touch 60/91 | **39%** · **43%** | −$424 · +$427 | −$8 · +$7 |
| 3-min | 2.0R | close 58/96 · touch 64/96 | **34%** · **41%** | −$34 · +$1,552 | −$1 · +$24 |
| 2-min | 1.0R | close 51/76 · touch 55/76 | **73%** · **69%** | +$2,724 · +$2,435 | +$53 · +$44 |
| 2-min | 1.5R | close 64/95 · touch 69/95 | **42%** · **52%** | +$194 · +$2,384 | +$3 · +$35 |
| 2-min | 2.0R | close 70/102 · touch 75/102 | **34%** · **49%** | −$48 · +$4,244 | −$1 · +$57 |

So: **the second trade wins about 40–50% of the time at a 1.5R target and about 60–70% at 1R —
roughly the same rate as the first trade, never materially worse, and better on the touch trigger.**
It triggers on 59–74% of stop-out days, so it is not a rare event; on the best cells it turned the
stop-out days from −$8,943 to −$6,559.

Two patterns hold across all six rows, which is what makes them worth acting on:

1. **Waiting for a close back through the level costs money.** `touch` beat `close` in every single
   combination, by 5 to 15 points of win rate. The confirmation gives up several points of the move
   and buys nothing.
2. **The re-entry is not the "revenge trade" it looks like.** Taken after the 15-minute cooldown it
   performs like a fresh signal, not a worse one. (Skipping the cooldown was tested on the small
   sample and lost money in every variant.)

And one that does not: the re-entry does not rescue the day. At best 37 of 75 stop-out days finished
green, because a 1R loss plus a 1.5R win is barely more than flat after commissions.

## What this does not say

The re-entry does not create an edge — it clones a breakeven one. The cells where it looks strongly
profitable (+$4,244 on 75 trades) are the same rule as the cells where it looks flat, so most of
that spread is noise: 152 sessions is one regime, the bars are the cash index rather than ES, and
the fills are simulated. Before changing the rule, run it in the Strategy Tester on your own years
of MES data.

If something is going to change, the first trade's expectancy is the target, not the second trade's.

## Reproduce

```bash
.venv/bin/python lab/deep_history.py --years 2                        # data/SP500_1min_deep.csv
.venv/bin/python lab/orb_reentry.py --csv data/SP500_1min_deep.csv
.venv/bin/python lab/orb_reentry.py --csv data/SP500_1min_deep.csv --target 1 --detail
.venv/bin/python lab/orb_reentry.py                                   # the 30-day Yahoo feed
```

`--min-bars` drops sessions the archive served with holes; the archive throttles hard, so 152 of the
522 weekdays in the window came back complete. Re-running `deep_history.py` on another day fills
more from the cache and the numbers above can be recomputed on the larger sample.
