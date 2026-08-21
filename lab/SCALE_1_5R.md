# Scaling out at 1.5R instead of 2R

The question came out of 2026-08-20: both trades ran past 1R and gave it all back. So the rule
now exists as `--exit scale_1.5R` — 75% off at 1.5R, the 25% runner left on a breakeven stop
that trails an R behind the best price, everything else identical to `scale_2R`.

## What it would have changed

Replay of `data/SP500_1min_deep.csv` (302 sessions, 178 of them traded), 2-minute range,
`--runner-pct 0.25 --orb-reentry`, both rules through the same gate:

| | `scale_2R` | `scale_1.5R` |
|---|---|---|
| net, all setups | **-$1,186.70** | **-$1,192.42** |
| trades | 212 (68W / 144L) | 211 (80W / 131L) |
| green days | 67 of 178 | 77 of 178 |
| qualifying days ($300+ net) | **14** | **5** |
| ORB + ORB2 net | -$319.93 | -$173.86 |
| ORB + ORB2 win rate | 32.8% | 39.3% |
| average win / loss (ORB) | +$271.07 / -$134.88 | +$205.97 / -$134.74 |

Read that as one trade-off, not two results: the closer target converts about six percentage
points of losses into wins and ten more green days, and pays for it by making every winner
about $65 smaller. On net the two rules land within $6 of each other over two years — the money
is a wash.

Where they are not a wash is the payout. A $300 **net** day needs roughly 2R on three
contracts, so cutting the scale-out to 1.5R takes most qualifying days off the table: 14 becomes
5. That is the cost worth arguing about, because Apex pays on qualifying days, not on win rate.

## On 2026-08-20 specifically

Neither rule changes that day. Trade 1 ran to +1.17R (7716.25 against a 7719.25 target) and
trade 2 to +1.37R (7719.75 against 7721.00) — both short of 1.5R, both back to the stop. What
would have saved that day is moving the stop to breakeven at 1R, which is a different rule and
is not what is implemented here.

## Caveats

Same ones as every study in `lab/`: the deep file is Dukascopy's cash S&P 500, not ES (about 23
points of basis, opening-range widths match within half a point), fills are simulated from
1-minute bars, and a bar covering both stop and target is scored as the stop. 178 traded days is
enough to show the shape of the trade-off and not enough to prove which rule is better.
