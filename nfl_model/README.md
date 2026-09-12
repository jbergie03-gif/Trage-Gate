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

## 3. `td_model.py` — anytime-touchdown probabilities

Follows the survey into the one cell that was both tight and liquid.

```
lambda = td_share(player) * expected_offensive_tds(team, game)
P(1+ TD) = logistic(a + b * log lambda)      # Platt-recalibrated
```

`td_share` is a player's share of his team's offensive TDs, built from prior
games only and shrunk toward a carries+targets usage prior, then normalized so a
team's shares sum to one. `expected_offensive_tds` comes from the market's
implied team total (`-0.653 + 0.1324 * implied_points`, fit pre-2018), because
the game-level result above says the line already holds that information.

```bash
python3 td_model.py
```

Out of sample, 2018–2026, 38,241 player-games (actual 1+TD rate 0.217):

| Predictor | Brier |
|---|---|
| Flat base rate | 0.17012 |
| Player's season-to-date rate | 0.16438 |
| Raw Poisson | 0.16069 |
| **Calibrated model** | **0.15924** |

So it beats the naive baselines — 6.4% Brier skill over the base rate — and its
calibration buckets track actual rates to within ~2 points below 0.4.

### But it does not beat the market. `live_props.py`

```bash
python3 live_props.py
```

Matching 225 of Kalshi's 331 quoted anytime-TD markets, week 1 2026:

| Market price | n | Market mean | Model mean | Model − market |
|---|---|---|---|---|
| 0–10c | 50 | 0.067 | 0.124 | **+5.6c** |
| 10–20c | 69 | 0.147 | 0.168 | +2.1c |
| 20–30c | 47 | 0.242 | 0.200 | −4.2c |
| 30–50c | 49 | 0.371 | 0.273 | −9.9c |
| 50c+ | 10 | 0.559 | 0.354 | **−20.5c** |

The disagreement is monotone in price, which is the signature of a model that is
*flatter* than the market, not one that knows better: model σ = 0.083 against
market σ = 0.134, correlation 0.78. The market spreads its probabilities twice
as wide and is calibrated, so the "edges" at both tails are the model's missing
information, not the market's error.

Two concrete gaps explain most of it:

- **No depth-chart or availability input.** The largest apparent edges land on
  backups the market knows won't get carries — including backup quarterbacks who
  are unlikely to take a snap. The model projects anyone with prior usage.
- **Roster changes.** Week-1 usage priors come from last season's team, so a
  player who changed roles or teams is mispriced by construction.

**Conclusion: not tradeable as-is.** The next inputs that would plausibly close
the gap are snap share, red-zone/goal-line carry share, and the nflverse injury
feed — not more tuning of the current features.

## 4. `week_log.py` — the public record

```bash
bash fetch_data.sh          # refresh the nflverse data first
python3 week_log.py         # append the next slate's model-vs-line to the log
python3 week_log.py --score # score completed games of the current season
```

Appends to `/home/ubuntu/ff/2026_Pickem_Log.md` before kickoff, so the hit rate
is auditable rather than remembered. Game-level only by design: no player is
named until inactives and depth charts are verified.

## Data sources

- [nflverse games.csv](http://www.habitatring.com/games.csv) — results plus
  closing spread/total/moneyline, 1999–present.
- [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases) —
  play-by-play, rosters, injuries, weekly player stats, through 2026.
- Kalshi public trade API — live books.

## Standing caveat

Backtested and modelled results do not demonstrate future profitability. Nothing
here places orders.
