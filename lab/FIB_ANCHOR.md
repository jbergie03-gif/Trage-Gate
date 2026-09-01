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
| `--fib-anchor pivots` | two confirmed swing pivots, 10 bars either side | dozens | the original rule |
| `--fib-anchor open15` (now live) | the day's high against the day's low, once the day has run 15 minutes | one | Jonathan's rule |

Everything downstream is the same for both: entry is the confirming close back out of the .618
zone, the stop is the far end of the leg ±0.25, the target is `--fib-target` × the leg, and the
1.5:1 gate, the trade limits, the cooldown and the sizing all still apply. Direction is
whichever extreme printed **later** — a low made after the high is a down move, so the bounce
is sold. Results 1 and 2 below use the original target (the leg extreme, `--fib-target 1.0`);
result 3 is the 1.272 extension that is now live.

The leg is frozen at the 15-minute mark by default. `--fib-anchor-extend` lets it follow the
day instead: a new high on an up leg extends the leg and re-arms the setup.

## Sample

`data/SP500_1min_deep.csv` — **302 sessions**, 2024-08-20 → 2026-08-14, 1-minute bars, fills
simulated from OHLC. This is Dukascopy's S&P 500 **cash index**, not ES/MES: the price level is
wrong by the futures basis and the point values here are MES's. Read it for shape, not for the
dollar figure. Every run goes into a throwaway journal; `paper_journal.db` is untouched.

Reproduce: `python lab/fib_anchor.py [--setups orb,fib] [--min-rr 1.25] [--fib-target 1.0]`

## Result 1: under the live 1.5:1 gate, the new anchor barely trades

Fib only, so the ORB neither hides nor helps it:

| anchor | setups | refused by 1.5:1 | trades | wins | net | avg R |
|---|---|---|---|---|---|---|
| pivots | 656 | 499 | 18 | 5 | **-$761** | -0.30 |
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
| pivots | 151 | 66 | **-$327** | 0.00 |
| open15 | 41 | 19 | +$508 | 0.12 |
| open15, fixed leg | 31 | 16 | +$931 | 0.25 |
| open30 | 24 | 12 | +$542 | 0.20 |
| open30, fixed leg | 20 | 12 | **+$1,077** | 0.44 |

And at 1.0:1, where nearly every setup is allowed through and the sample is largest:

| anchor | trades | wins | net | avg R |
|---|---|---|---|---|
| pivots | 231 | 103 | **-$1,078** | -0.02 |
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

## Result 3: the 1.272 target unblocks the gate without touching it

The reason to prefer this over lowering the gate: aiming past the leg extreme raises the ratio
of the setup itself, so the same 1.5:1 rule that was refusing everything now passes it. Gate
back at the live **1.5:1**, target at 1.272 of the leg, Fib only:

| anchor | setups | refused by 1.5:1 | trades | wins | net | avg R |
|---|---|---|---|---|---|---|
| pivots | 506 | 136 | 228 | 82 | +$101 | 0.02 |
| **open15, fixed leg (live)** | 146 | 31 | **57** | 24 | **+$1,325** | **0.17** |
| open15, extending | 216 | 39 | 70 | 29 | +$1,356 | 0.17 |
| open30, fixed leg | 115 | 17 | 34 | 17 | +$2,070 | 0.43 |
| open30, extending | 144 | 15 | 40 | 18 | +$1,404 | 0.26 |

Refusals collapse from 58% of open15 setups to 21%, and the Fib becomes a rule that actually
fires: **57 trades over 302 sessions** on the fixed 15-minute leg, against 4 with the old
target. Pivot legs stay worth about zero R per trade whatever the target is.

With the ORB running alongside it, which is the day as it would actually trade — the last two
columns are every trade the day took, ORB included:

| anchor | Fib trades | wins | Fib net | avg R | day net | $300+ days |
|---|---|---|---|---|---|---|
| pivots | 184 | 63 | **-$1,254** | -0.03 | +$380 | 28 |
| open15, fixed leg (live) | 15 | 7 | +$381 | 0.21 | +$2,015 | 19 |
| open15, extending | 27 | 16 | +$2,068 | 0.65 | **+$3,702** | 19 |
| open30, fixed leg | 20 | 9 | +$776 | 0.29 | +$2,410 | 17 |
| open30, extending | 26 | 12 | +$868 | 0.27 | +$2,502 | 17 |

Every day-range variant is positive and pivots is not, at every gate and both targets tested.
That consistency is worth more than any single cell in these tables. Note that the ORB takes
most of the day's trades, so the Fib's own count drops to 15 once the day's limits and locks
are competing with it: this change buys roughly **one Fib trade a month**, not a new engine.

The extension target is on the tick grid, rounded away from entry — 0.272 of a leg lands
anywhere, and a target off the 0.25 grid is not a price anyone can be filled at.

## What is fact and what is not

- **Fact, measured:** the 1.5:1 gate refuses the large majority of Fib setups under either
  anchor, and open15 with the live gate is effectively a rule that never fires.
- **Fact, measured:** across 20–231 trade samples at looser gates, open15 legs have a positive
  average R and pivot legs do not.
- **Fact, measured:** the 1.272 target raises the setup's own ratio enough to clear the 1.5:1
  gate, so the gate never had to be weakened.
- **Not established:** that any of this makes money. The live variant's figure is +$1,325 over
  two years on approximate cash-index data, on 57 trades, and only 15 of those trades survive
  once the ORB is competing for the day's limits. That is inside the noise, and it is a
  simulation on the wrong instrument. Nothing here is evidence of an edge.
- **Not established:** fixed leg vs extending leg, or 15 minutes vs 30. Fixed and open30 look
  better on Fib-only R, while the extending leg is the best full-day result in the table (15
  trades vs 27 is most of the difference). The samples are 15 to 57 trades and they disagree
  depending on whether the ORB is running.

## What was changed, 2026-08-31

On Jonathan's instruction the live defaults are now:

```
--fib-anchor open15 --fib-anchor-minutes 15   # the day's range, leg fixed at 06:45 PT
--fib-target 1.272                            # the extension past the leg extreme
```

The daily automation passes no Fib flags, so it picks these up. `--fib-anchor pivots`,
`--fib-anchor-extend` and `--fib-target 1.0` restore the old behaviour piece by piece.

The reasoning for keeping the 1.5:1 gate and changing the target instead of lowering the gate:
lowering a risk gate so that setups qualify is fitting the rule to the data, while the
extension target is a claim about where the move goes — which is a thing the history can test,
and did.

**The argument against, plainly:** the Fib now exits past the end of the leg it is retracing,
so it only pays when the move continues rather than merely returns. The win rate is under 50%
on every variant here, and the whole result rests on a handful of large winners in a two-year
simulation. If the Fib is still not producing in a month of live paper sessions, the honest
answer is to retire it and let the ORB carry the system, not to loosen another rule.

Worth measuring next, in this order: the **extending leg** (best full-day net here, and the
reason is simply that it takes more trades) and **30 minutes instead of 15** (better Fib-only R
in most tables). Neither was adopted: Jonathan's rule says 15 minutes, the fixed leg is the
literal reading of it, and every gap involved is inside the noise of these samples.
