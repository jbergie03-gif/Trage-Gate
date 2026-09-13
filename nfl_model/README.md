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

## 4. `features.py` + `td_logit.py` — adding scoring role (v2)

The flatness above says the model can't tell *who scores* from *who plays*. So
v2 replaces the single usage share with a logistic fit on features that describe
scoring role, keeping team touchdowns from the market's implied total:

| Feature | Source |
|---|---|
| red-zone target share (inside the 20) | play-by-play |
| goal-line carry share (inside the 5) | play-by-play |
| offensive snap share | `snap_counts` |
| carry / target / TD share | weekly player stats |
| position (QB, RB, TE) | weekly player stats |

Every player feature is a prior-games-only trailing window that **spans the
season boundary** — a season-to-date total is zero in week 1, exactly when the
model is used.

```bash
python3 features.py    # cache red-zone/goal-line usage from play-by-play
python3 td_logit.py    # fit 2016-2019, test 2020-2026
```

Fit on 16,743 player-games (2016–2019), tested on 29,544 (2020–2026):

| Predictor | Brier | σ of predictions |
|---|---|---|
| Flat base rate | 0.16854 | 0 |
| v1 usage share | 0.15792 | 0.088 |
| **v2 scoring role** | **0.15507** | **0.105** |

Calibration holds at the wider spread (predicted vs actual: 0.083/0.083,
0.149/0.139, 0.244/0.250, 0.343/0.376, 0.443/0.474, 0.554/0.554).

### Which of the new features actually paid

Drop a feature, refit, rescore the same test rows:

| Dropped | Brier | Δ |
|---|---|---|
| snap share | 0.15525 | +0.00019 |
| position dummies | 0.15512 | +0.00005 |
| goal-line carry share | 0.15507 | ±0.00000 |
| red-zone target share | 0.15505 | **−0.00002** |
| TD share | 0.15553 | +0.00047 |

**Red-zone target share adds nothing measurable** — not for WRs (+0.00003), not
for TEs (−0.00005), not for the top quartile of red-zone share (+0.00002), not
on the high-priced end of the board (−0.00013). The intuition is right about who
scores; the information is simply already inside target share and TD share,
which is why adding it is redundant rather than wrong. Snap share is the only
new input that helps, and it helps by 0.1% of Brier.

So most of v2's gain came from the functional form, not the new data.

### v2 against the live market. `live_props_v2.py`

Same 225 matched Kalshi books, week 1 2026, now with players listed Out or
Doubtful on the injury report dropped:

| | v1 | v2 | market |
|---|---|---|---|
| mean | 0.196 | 0.217 | 0.214 |
| σ | 0.083 | **0.105** | 0.134 |
| correlation with market | 0.78 | **0.86** | — |

| Market price | n | Market | v2 model | v2 − market | (v1 − market) |
|---|---|---|---|---|---|
| 0–10c | 51 | 0.067 | 0.130 | +6.3c | +5.6c |
| 10–20c | 69 | 0.147 | 0.174 | +2.7c | +2.1c |
| 20–30c | 47 | 0.242 | 0.222 | −2.0c | −4.2c |
| 30–50c | 48 | 0.368 | 0.308 | −6.0c | −9.9c |
| 50c+ | 10 | 0.559 | 0.492 | −6.7c | −20.5c |

The favorite-end bias shrank from −20.5c to −6.7c and the longshot bias did not
improve at all. The residual pattern is still monotone, so **v2 is closer to the
market but still flatter, and still not tradeable.** The remaining large
disagreements concentrate on rushing quarterbacks and goal-line backs, i.e.
short-yardage role, which neither snap share nor season-long goal-line share
captures for week 1.

## 5. `injuries.py` — pricing the injury report

```bash
python3 injuries.py                  # writes data/injury_burden.csv
```

Counting injured bodies measures nothing: a team can list eight names and lose
nobody who plays. Each player on the report is instead weighted by the snap
share he had been taking, and by how often his designation actually sits (Out
1.0, Doubtful 0.75, Questionable 0.25). The quarterback is excluded because he
is already a first-class model input.

Two joins are worth knowing about, because both were wrong on the first pass:

- The injury feed keys players by `gsis_id`, the snap feed by `pfr_id`, so they
  go through nflverse's player crosswalk. Name matching linked 29% of rows; the
  crosswalk links 96.5%.
- A player who is Out has no snap row for the game he missed, so the share
  cannot be looked up by week — it walks back to his most recent cumulative
  average, then to last season's. Without that the players who matter most are
  exactly the ones missing from the join.

**Measured effect, 1,962 held-out games:** correctly signed and statistically
real — the away team missing more of its offense lifts the home margin by 0.60
points per standard deviation (z = 2.9), defense 0.48 (z = 2.3), which ranks
them behind only the efficiency metrics and the quarterback. **But accuracy does
not improve:** margin MAE 10.247 → 10.232, totals unchanged, ATS 48.9% → 48.2%.
The effect is real and too small to see through 10 points of noise. Kept in the
design matrix, since the case it exists for is the one game where a team is
missing three starters.

Known limitation: all snaps are valued equally, so a left tackle and a fourth
receiver at the same snap share count the same.

## 6. `week_log.py` — the public record

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
