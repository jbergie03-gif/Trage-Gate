# Where the Fib is drawn from: swing pivots, or the day's own range

Jonathan's instruction, 2026-08-31: *"lets do the opening bar with the high or low of the day
after 15 minutes of trading. draw the fibs based off those pivot points."*

It came out of that day's session, where the Fib found five setups and took none of them. All
five were refused by the 1.5:1 reward:risk gate. That is not bad luck, it is the geometry: with
the stop at the far end of the leg and the target at the near end, the best ratio the rule can
ever offer is 0.618 / 0.382 = **1.62:1**, and only if the fill is exactly at the .618. The 0.25
stop buffer and waiting for a confirming close eat the rest, so on the 7–11 point pivot legs
that day nothing could pass.

## The two rules

| | anchor | legs per day | what it is |
|---|---|---|---|
| `--fib-anchor pivots` (live) | two confirmed swing pivots, 10 bars either side | dozens | the original rule |
| `--fib-anchor open15` | the day's high against the day's low, once the day has run 15 minutes | one, extended as the day extends | Jonathan's rule |

Everything downstream is unchanged: entry is the confirming close back out of the .618 zone,
the stop is the far end of the leg ±0.25, the target is the leg extreme, and the 1.5:1 gate,
the trade limits, the cooldown and the sizing all still apply. Direction is whichever extreme
printed **later** — a low made after the high is a down move, so the bounce is sold.

`--fib-anchor-fixed` freezes the leg at the 15-minute mark. Without it the leg follows the day:
a new high on an up leg extends the leg and re-arms the setup.

## Sample

`data/SP500_1min_deep.csv` — **302 sessions**, 2024-08-20 → 2026-08-14, 1-minute bars, fills
simulated from OHLC. This is Dukascopy's S&P 500 **cash index**, not ES/MES: the price level is
wrong by the futures basis and the point values here are MES's. Read it for shape, not for the
dollar figure. Every run goes into a throwaway journal; `paper_journal.db` is untouched.

Reproduce: `python lab/fib_anchor.py [--setups orb,fib] [--min-rr 1.25]`

## Result 1: under the live 1.5:1 gate, the new anchor barely trades

Fib only, so the ORB neither hides nor helps it:

| anchor | setups | refused by 1.5:1 | trades | wins | net | avg R |
|---|---|---|---|---|---|---|
| pivots (live) | 656 | 499 | 18 | 5 | **-$761** | -0.30 |
| open15 | 221 | 107 | 5 | 2 | +$7 | 0.01 |
| open15, fixed leg | 146 | 84 | 4 | 2 | +$122 | 0.26 |
| open30 | 146 | 53 | 3 | 1 | -$70 | -0.16 |
| open30, fixed leg | 115 | 46 | 5 | 2 | -$12 | 0.01 |

With the ORB switched back on — the day as it would actually trade — open15 takes **0 to 2
Fib trades in two years**.

**The gate, not the anchor, is what stops the Fib trading.** Both rules produce plenty of
setups; 76% of pivot setups and about half of open15's are refused for reward:risk, and the
day's limits take most of the rest. Changing the anchor alone changes almost nothing, because
the geometry that caps the ratio at 1.62:1 is the same in both.

## Result 2: with the gate at 1.25:1, the anchors separate clearly

Same runs, `--min-rr 1.25` (a study override through `TRADE_GATE_CONFIG`; the live config is
not touched):

| anchor | trades | wins | net | avg R |
|---|---|---|---|---|
| pivots (live) | 151 | 66 | **-$327** | 0.00 |
| open15 | 41 | 19 | +$508 | 0.12 |
| open15, fixed leg | 31 | 16 | +$931 | 0.25 |
| open30 | 24 | 12 | +$542 | 0.20 |
| open30, fixed leg | 20 | 12 | **+$1,077** | 0.44 |

And at 1.0:1, where nearly every setup is allowed through and the sample is largest:

| anchor | trades | wins | net | avg R |
|---|---|---|---|---|
| pivots (live) | 231 | 103 | **-$1,078** | -0.02 |
| open15 | 70 | 33 | +$577 | 0.07 |
| open15, fixed leg | 54 | 26 | +$599 | 0.10 |
| open30 | 41 | 20 | +$576 | 0.12 |
| open30, fixed leg | 34 | 18 | +$982 | 0.22 |

The sign is stable across both gates and all four day-range variants: **pivot legs are worth
about zero R per trade and open15 legs are worth +0.1 to +0.4 R.** That is the useful finding,
and it is the one Jonathan's read of the chart predicted — a retracement of the day's actual
move is a different animal from a retracement of a five-minute wiggle.

The strongest single variant, ORB + Fib together at a 1.25 gate, is the fixed 15-minute leg:
9 trades, 6 winners, +$628, +0.58 R average. **Nine trades is not evidence.** Treat the
per-trade R across the larger samples as the signal and the dollar totals as noise.

## What is fact and what is not

- **Fact, measured:** the 1.5:1 gate refuses the large majority of Fib setups under either
  anchor, and open15 with the live gate is effectively a rule that never fires.
- **Fact, measured:** across 20–231 trade samples at looser gates, open15 legs have a positive
  average R and pivot legs do not.
- **Not established:** that open15 makes money. The positive nets are a few hundred dollars
  over two years on approximate cash-index data — well inside the noise, and they only exist at
  a gate looser than Jonathan's rule.
- **Not established:** fixed leg vs extending leg. Fixed looks better in every table, but the
  gap is a handful of trades wide.

## Recommendation

Switch the anchor to `--fib-anchor open15 --fib-anchor-fixed`, and **at the same time** deal
with the gate, because the anchor on its own does nothing. Two ways to do that:

| option | what it does | why / why not |
|---|---|---|
| lower the gate to 1.25:1 for the Fib | lets the geometry's realistic ratios through | measured above: 31 trades, +0.25 R. But it weakens a risk rule that exists for good reason, and it applies to the ORB too unless it is made setup-specific |
| target the 1.272 extension of the leg instead of the leg extreme | pushes R:R to ~2.3:1, so setups pass the 1.5 gate untouched | keeps the risk rule intact; changes what the trade is aiming at, and is unmeasured |

**Recommended:** keep the 1.5:1 gate and change the target — measure the 1.272 extension on
open15 legs next, and only fall back to lowering the gate if the extension target does not
clear it. Lowering a risk gate to make setups qualify is fitting the rule to the data; the
extension target is a claim about where the move goes, which is the thing actually being
tested.

**The argument against:** the extension target means the Fib no longer exits where the leg
ends, so the win rate will fall and the trade only pays if the move genuinely runs past its own
extreme. If that does not hold up in the next study, the honest answer is not to lower the gate
but to retire the Fib and let the ORB carry the system.

## Not changed

The daily run still uses `--fib-anchor pivots`. Nothing here moves the live rule until Jonathan
says so.
