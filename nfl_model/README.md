# NFL prediction research

Two questions, answered with measurements rather than assertions:

1. Can a cheap ratings model beat the closing spread? **No.**
2. Which NFL markets are loose enough to be worth modelling at all?

Read-only, public data, no credentials, no order placement.

## 1. `elo.py` — game model vs the closing line

Walk-forward Elo with margin-of-victory damping and between-season reversion,
scored against nflverse closing spreads. Ratings at prediction time never see
the result.

```bash
python3 elo.py --start 2015          # all games
python3 elo.py --start 2015 --edge 6 # only where the model disagrees by 6+
```

Out of sample, 2015–2025, 3,030 games:

| | RMSE vs actual margin |
|---|---|
| Elo model | 13.24 pts |
| **Closing spread** | **12.72 pts** |

The market is more accurate than the model. Filtering to larger disagreements
raises the hit rate but never significantly past break-even (52.38% at -110):

| Model edge | Bets | ATS% | z vs break-even |
|---|---|---|---|
| ≥0 | 2954 | 49.63% | −2.99 |
| ≥3 | 1202 | 51.16% | −0.84 |
| ≥5 | 500 | 54.20% | +0.81 |
| ≥7 | 204 | 57.84% | +1.56 |

Nothing clears 2 sigma, and the pattern isn't monotone (≥8 falls back to
54.24%) — consistent with noise, not edge.

The decisive test regresses actual margin on the market line plus the model's
deviation from it:

```
actual_margin = -0.10 + 1.067 * market_spread + 0.090 * (model - market)
                                    t=23.6            t=1.25
```

The market coefficient is ≈1 (unbiased). The model's disagreement with the
market carries **no significant information** (t=1.25). Anything this model
says that the line doesn't already say is noise.

**Conclusion: do not bet game spreads off this model.** Reproduce with the
commands above before believing it.

## 2. `market_survey.py` — where the soft markets are

Spread width is the toll to enter; open interest is whether size is available.

```bash
python3 market_survey.py
```

Measured on live Kalshi books, Sat Sep 12 2026:

| Market | Median spread | Median open interest |
|---|---|---|
| Game winner | 1.0c | 24,051 |
| Game spread | 2.0c | 1,589 |
| Game total | 1.0c | 655 |
| Player anytime/2+ TD | 1.0c | 771 |
| Player first TD | 2.0c | 234 |
| Player rushing attempts | 11.0c | 0 |
| Longest rush | 3.0c | 0 |

Read: game winners are efficient and crowded. Rushing attempts and longest rush
are quoted wide but have **no open interest** — soft and untradeable, which is
the usual trap. Anytime-TD props are the interesting cell: 1c wide with real
open interest, so an accurate probability is worth something there.

## Data sources

- [nflverse games.csv](http://www.habitatring.com/games.csv) — results plus
  closing spread/total/moneyline, 1999–present.
- [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases) —
  play-by-play, rosters, injuries, weekly player stats, through 2026.
- Kalshi public trade API — live books.

## Standing caveat

Backtested and modelled results do not demonstrate future profitability. Nothing
here places orders.
