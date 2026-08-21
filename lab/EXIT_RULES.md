# Every exit rule, over 178 traded days

The question this answers: with the entry rules held exactly as they are — 2-minute opening
range, one break, one same-direction re-entry, the Fib pullback, the same day limits and the
same $150 risk — how much of the difference in results is the *exit*?

Data: `data/SP500_1min_deep.csv`, the Dukascopy cash-index feed (`lab/deep_history.py`), 302
complete sessions from 2024-08-20 to 2026-08-14, of which 178 produced a trade. Every rule was
run over the identical bars with `--orb-reentry --runner-pct 0.25`:

```
TRADE_GATE_DB=/tmp/<rule>.db TRADE_GATE_REPORTS=/tmp/<rule> \
  .venv/bin/python paper_engine.py --replay data/SP500_1min_deep.csv --speed 0 \
  --orb-reentry --runner-pct 0.25 --reset --exit <rule>
```

## What each rule kept

| exit rule | net $ | trades | win % | qualifying days | green days | worst drawdown |
|---|---|---|---|---|---|---|
| `opposite_end` | **+8,070** | 199 | 20.1% | 27 | 39 | −4,076 |
| `trail_after_1R` | **+1,983** | 206 | 44.2% | 18 | 81 | −1,572 |
| `trail_after_1R --trail-r 0.5` | +115 | 208 | 48.6% | 6 | 87 | −1,644 |
| `be_1R` | −216 | 210 | 27.1% | 2 | 55 | −2,248 |
| `scale_2R` (live) | −1,187 | 212 | 32.1% | 14 | 67 | −3,222 |
| `scale_1.5R` | −1,192 | 211 | 37.9% | 5 | 77 | −3,132 |

Win % counts every closed trade, so the scale rules' runners count separately. Qualifying days
are $300+ **net** — the only days Apex pays on.

## The part that matters more than the ranking

Both winning rules are carried by a handful of trades:

| exit rule | net | net without its 3 best trades | biggest single trade | 1st half / 2nd half |
|---|---|---|---|---|
| `opposite_end` | +8,070 | **−1,562** | +3,412 | +6,702 / +1,368 |
| `trail_after_1R` | +1,983 | **−60** | +784 | +1,195 / +788 |
| `trail_after_1R 0.5` | +115 | −1,477 | +634 | +263 / −149 |
| `be_1R` | −216 | −1,095 | +295 | +40 / −256 |
| `scale_2R` | −1,187 | −2,421 | +431 | −833 / −354 |
| `scale_1.5R` | −1,192 | −2,305 | +389 | −601 / −592 |

So `opposite_end`'s whole result is three trades: take them away and it loses money like
everything else. `trail_after_1R` is the same story in miniature — but it is the only rule that
was profitable in *both* halves of the sample, and it has the smallest drawdown of the six by a
wide margin, on 44% winners rather than 20%. That is a rule that survives a bad month; the
opposite-end rule needs one enormous trend day to pay for the quarter.

## What this says about the two questions asked

1. **Does the 1.5R scale-out fix the trades that hand back 1.2–1.4R?** No. It wins more often
   (37.9% vs 32.1%) but the wins are smaller, net lands within $6 of `scale_2R`, and qualifying
   days fall 14 → 5, because $300 net needs about 2R at $150 of risk. Detail in
   `lab/SCALE_1_5R.md`.
2. **Does moving the stop to breakeven at 1R fix them?** It stops the bleeding — net improves
   from −1,187 to −216 — but it does it by turning would-be winners into scratches: 27% winners
   and 2 qualifying days. Protecting the entry is not the same as making money.

What actually helped was not banking at a fixed multiple at all: **let the trade run and follow
it with a stop an R behind the high once it has paid an R**. That is `trail_after_1R`, and
tightening it to half an R (`--trail-r 0.5`) gives back nearly all of the gain, which is the
same lesson from the other direction — the edge here, such as it is, lives in the few trades
that run a long way.

## What this is not

- The prices are a **cash-index CFD**, not ES. Basis is ~23 points, opening-range widths matched
  ES within half a point on the overlapping days, and everything above is measured in R, but it
  is still not the instrument being traded.
- Fills are **simulated from 1-minute OHLC**. A bar that covers both the stop and the target is
  scored as the stop, which is pessimistic, but a real fill on a fast bar can be worse than any
  of these numbers.
- 178 traded days is one market regime — a long grind higher with two corrections. It is enough
  to reject a rule, not enough to trust one.
- No commissions beyond the round-trip in `config.json`, no slippage, no partial fills.

## How the daily report uses this

`paper_engine.py --today` now replays the day it just recorded under `scale_1.5R`, `be_1R` and
`trail_after_1R` (`--compare-exits` changes the list, an empty string switches it off) and
appends the comparison to the session report. Those replays run in throwaway journals seeded
from the real one, so the record stays on the live rule and only the live rule ever writes to
`paper_journal.db`.
