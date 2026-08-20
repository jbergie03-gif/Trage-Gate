# Does the second ORB trade in the same direction pay?

Question: the first opening-range break fails often — what happens if you take the second break in
the same direction after it stops out?

Measured by `lab/orb_reentry.py` on `data/ES_1min_recent.csv`: **21 sessions, 2026-07-22 →
2026-08-19**, the whole month of 1-minute futures history the free feed serves. Stops capped at 12
points, ~$150 of risk per trade, commissions in, a bar covering both the stop and the target scored
as the stop, and the engine's 15-minute post-loss cooldown applied before the re-entry.

## The first trade fails about half the time

| Opening range | Broke | Stopped out | Hit 1.5R | Net |
|---|---|---|---|---|
| 3-minute | 21/21 | **11 (52%)** | 9 (43%) | +$367 |
| 2-minute | 21/21 | **11 (52%)** | 10 (48%) | +$371 |

So Jonathan's read is right: roughly half the first trades stop out. At a 2R target it is 62%.

## The re-entry is a coin flip in this sample

Two triggers, both same direction and taken once: `close` = a bar closes back through the broken
level (what `--orb-reentry` does today), `touch` = price simply trades back through the level.

| Range | Target | Cooldown | Triggered | Re-entry win rate | Re-entry net |
|---|---|---|---|---|---|
| 3-min | 1.5R | 15 min | 7 of 11 | close 3/7 (43%) · touch 4/7 (57%) | +$274 · +$419 |
| 2-min | 1.5R | 15 min | 8 of 11 | close 3/8 (38%) · touch 4/8 (50%) | −$70 · +$296 |
| 3-min | 2R | 15 min | 7–9 of 13 | close 3/7 (43%) · touch 3/9 (33%) | +$465 · +$263 |
| 2-min | 1.5R | none | 8 of 11 | close 2/7 (29%) · touch 3/8 (38%) | −$70 · −$42 |

**The headline number is 3 to 4 wins out of 7 or 8 — call it 40–55%, and it moves by 20 points when
any assumption moves.** On the best-looking variant (3-minute range, touch trigger) the re-entry
turned the 7 losing days from −$837 to −$418 and finished 4 of 7 green; on the worst (no cooldown)
it lost money. Sign flips like that across nearly identical settings are what a sample this size
looks like when there is no measurable edge.

## What it does say

- The cooldown helps. Every variant with the 15-minute wait beat the same variant without it —
  consistent with the second break working when it comes after a pause, not as revenge.
- Taking the re-entry at the level (`touch`) beat waiting for a close back through it in 3 of 4
  variants. The close trigger gives up several points of the move for its confirmation.
- Re-entering does not rescue the day. Best case, 4 of 7 stop-out days finished green.

## What it does not say

7–9 re-entries over one month of one regime, on simulated fills from a delayed feed, cannot support
a rule change — 2 trades landing differently swings the win rate 25 points. Before changing the ORB
rule, run it in the Strategy Tester on years of MES data. Until then the honest answer to "is the
second trade better?" is **not knowable from this sample**.

## Reproduce

```
.venv/bin/python lab/orb_reentry.py                 # 3- and 2-minute ranges, 1.5R, 15-min cooldown
.venv/bin/python lab/orb_reentry.py --detail        # per-session table
.venv/bin/python lab/orb_reentry.py --target 2 --cooldown 0
.venv/bin/python lab/orb_reentry.py --fetch         # refresh the CSV first
```
