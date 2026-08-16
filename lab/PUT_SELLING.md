# Selling puts for income: what the arithmetic allows on a small account

Reproduce with, from the repo root:

```bash
.venv/bin/python lab/put_selling.py --account 2500 --symbols SPY   # the strategy over 34 years
PYTHONPATH=lab .venv/bin/python lab/put_screen.py --account 2500   # what $2,500 can reach today
```

## The strategy being tested

Sell a cash-secured put roughly 10 days out at about 10 delta, on a name you would be willing to
own. Ten delta means about a 90% chance of expiring worthless, so the premium is kept about nine
times out of ten. If it expires in the money you are assigned the shares at the strike. Cash
secured means the account holds **strike × 100** in cash for every contract, which is the number
that decides everything on a small account.

Two things this test does *not* do, both deliberately: it does not close winners early at a profit
target, and it does not pick entries. Closing at "+100%" raises the win rate and leaves the tail
untouched, and the tail is the entire question.

## Pricing model, stated plainly

There is no free historical options data, so premiums come from Black-Scholes using VIX as the
volatility input, multiplied by a skew factor because out-of-the-money puts trade richer than
at-the-money ones. The skew factor is unknowable in retrospect, so every result is shown at ×1.0,
×1.3 and ×1.6. **These are modelled prices, not fills.** They get the order of magnitude and the
shape of the risk right; they are not a track record.

## SPY, 10 delta, 10 DTE, 1,205 trades over 34 years

| skew | win % | avg premium | return on collateral | worst trade | worst trade in weeks of premium |
|---|---|---|---|---|---|
| ×1.0 | 92.1% | $24 | 1.5%/yr | −$2,739 | 113 |
| ×1.3 | 97.7% | $32 | 4.7%/yr | −$2,455 | 76 |
| ×1.6 | 98.7% | $40 | 7.3%/yr | −$2,174 | 54 |

**SPY buy and hold over the same window: 10.9% a year.**

So even on the most generous premium assumption, selling puts on the index returned less than
owning the index — while requiring 36 decisions a year instead of none. The 92% win rate is real
and it is also irrelevant, which is the whole lesson: **one bad trade cost between 54 and 113 weeks
of premium.** The strategy spends a year and a half collecting what a single February 2020 takes
back.

Only 3 of 34 calendar years lost money (2007, 2015, 2018 — worst −$825), and the median year made
+$468 on $16,484 of collateral, about 2.8%. Note what *isn't* in the losing list: 2008. Selling
10-delta puts through the financial crisis was fine, because VIX at 80 puts the 10-delta strike so
far away that almost nothing reaches it. **The danger is not a crisis, it is a fast fall out of
calm** — the worst trade opened on 18 February 2020 with VIX at 19, and settled 12% lower.

## What $2,500 can actually reach

Collateral is strike × 100, so a $2,500 account needs a strike under $25. Priced at 10 delta and
10 DTE on each name's own realised volatility:

| symbol | spot | vol | strike | collateral | contracts | premium/trade | % of collateral | income/yr if nothing goes wrong | worst 10-day fall (5yr) | cost if that repeats |
|---|---|---|---|---|---|---|---|---|---|---|
| MARA | $9.20 | 87% | 7.37 | $737 | 3 | $6.20 | 0.84% | $670 | −44% | −$642 |
| RIVN | $15.36 | 67% | 12.90 | $1,290 | 1 | $8.57 | 0.66% | $308 | −47% | −$467 |
| LCID | $6.22 | 82% | 5.04 | $504 | 4 | $2.99 | 0.59% | $430 | −40% | −$502 |
| SOFI | $18.29 | 59% | 15.66 | $1,566 | 1 | $9.04 | 0.58% | $326 | −31% | −$291 |
| AAL | $14.83 | 52% | 12.94 | $1,294 | 1 | $5.56 | 0.43% | $200 | −30% | −$256 |
| F | $14.37 | 35% | 13.10 | $1,310 | 1 | $2.64 | 0.20% | $95 | −31% | −$319 |
| T | $24.89 | 24% | 23.35 | $2,335 | 1 | $3.53 | 0.15% | $127 | −15% | −$218 |
| KVUE | $19.20 | 29% | 17.80 | $1,780 | 1 | $3.06 | 0.17% | $110 | −15% | −$139 |

Out of reach entirely, because one contract needs more cash than the whole account: PFE ($2,514),
SIRI ($2,550), XLF ($5,551), BAC ($6,036), TQQQ ($6,483), INTC ($8,560), IWM ($28,819),
QQQ ($68,940), **SPY ($74,257)**.

## What the table is really saying

**The premium ranking is the volatility ranking, exactly.** MARA pays 5.6× what Ford pays because
MARA can fall 44% in ten days and Ford cannot. There is no name on that list that pays well and is
safe to be assigned, and there never will be, because the premium *is* the compensation for the
assignment risk. "Worst case I own the shares" is doing a lot of work in that sentence.

**One event costs about a year of income.** MARA: $670 a year of premium against $642 lost if its
own worst ten-day fall — which already happened, within the last five years — happens once while a
put is open. That is not a tail scenario, it is the base rate for that stock.

**Below about $5 a share the costs eat the trade.** GRAB at $3.62 prices to a *negative* premium
after $0.65 commission and two cents of spread. Penny-priced options are not a small-account
shortcut.

**One position, no diversification.** At $2,500 the account is one contract on one name at a time.
The concentration is forced, and it is the opposite of how this strategy is supposed to be run.

## The honest comparison with what Rich is doing

His numbers are $60k of AMD shares becoming $145k, plus $40k of premium. **The shares made $85,000
and the puts made $40,000** — and selling puts on a stock that doubled cannot lose. Scaled to
notional, his $2k a week is premium on roughly $200k of collateral, which is about 1% a week on
capital 80× this account. The strategy does not shrink: at $2,500 the same approach on the same
kind of names yields **$100–670 a year**, and a single assignment takes most of it back.

A 100% win rate on a strategy whose entire risk is a rare large loss is not evidence that it works.
It is evidence that the rare loss has not happened yet.

## Limits of this test

- Modelled prices, not fills. Real bid/ask on a $5 stock's weekly option is worse than two cents.
- Held to expiry; no early close, no roll, no defensive adjustment. A skilled operator rolls down
  and out, which changes the loss distribution and cannot be tested without real chain data.
- The screen uses five years of realised volatility as the implied-volatility input, so any name
  whose vol regime has changed is mispriced here.
- Assignment is settled as intrinsic value at expiry rather than modelling holding the shares and
  selling calls against them (the wheel). That understates the recovery and overstates the loss on
  names that bounce.
- **None of this can run in a Robinhood agentic account anyway**: selling a put is a short option,
  and the agentic MCP places long equities and options only.
