# NFL prediction research

Two questions, answered with measurements rather than assertions:

1. Can a cheap ratings model beat the closing spread? **No.**
2. Which NFL markets are loose enough to be worth modelling at all?

Read-only, no order placement. Public data throughout, with one exception:
`fantasyguru_pull.py` signs into Jonathan's paid Fantasy Guru account, with
their written permission and on a leash (section 9).

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

## 7. `market_flow.py` — public tickets vs where the line went

```bash
python3 market_flow.py --save            # next slate: public %, open -> close
python3 market_flow.py --history 2019 2020 2021 2022 2023 2024 2025
python3 market_flow.py --study           # grade every cut against the close
```

Two numbers that get conflated as "sharp money", kept apart: the share of
spread *tickets* on each side, and what the books did about it. Where they
point opposite ways — public on one side, the number moving the other — is
reverse line movement, the only observable trace of non-public money in free
data. Tickets are not dollars, so a 77% ticket share can be a minority of the
handle; none of these columns is a dollar figure.

Two traps the parser has to survive, both of which silently invent line
movement if ignored:

- The price history interleaves **alternate handicaps** with the main line —
  the same game at +8.5 for −476 and +14.5 for −1400 seconds apart. Only
  quotes priced near even money are the real line.
- The first tick is a **May lookahead number**, not an opener. The opener that
  means anything is the one hung for the week, so the walk back stops eight
  days out.

### What the signals are worth, 2019–2025

1,537 games (318 dropped: where the scraped close and the graded close
disagree by more than a half point, whichever is stale is stale *in the
direction of the move*, and backing a two-point mover scores a fictional
78.8%). Break-even at −110 is 52.4%.

| Cut | Cover | n |
|---|---:|---:|
| Public 50–60% (the popular side) | 54.2% ±2.3 | 471 |
| Public 60–70% | 46.7% ±2.6 | 362 |
| Public 70%+ | 46.7% ±5.8 | 75 |
| Backing a 0.5–2 pt move | 53.4% ±1.8 | 788 |
| Backing a 2+ pt move | 52.8% ±2.7 | 341 |
| **Reverse line movement** | **57.9% ±4.0** | 159 |
| Over, public 65%+ on the over | 46.0% ±4.7 | 113 |

The shape is the familiar one: fading a heavily-backed public side is mildly
positive, and lopsided public overs go under. Neither clears break-even by
more than a standard error.

Reverse line movement is the one cut that looks like an edge, and it does not
survive being split by season — 33%, 61%, 61%, 51%, 71% across 2021–2025,
with the largest season (n=49) at 51.0%. A signal that is real does not need
one season to carry it. Treated as information to report, not a bet: it earns
its place only from a logged forward record.

### Where it shows up

Not as a second report. `note()` turns a game's row into one sentence, or
returns nothing, and `slate_notes()` hands those to `week_log.py` so the
weekly log carries a market note in the same row as the prediction. A note is
written only for a crowd at 65%+, a line that moved a point or more, a
lopsided over, or the two disagreeing; on a typical slate that is four or five
games out of sixteen and the rest are silent. Each note quotes the cover rate
and sample size for its own cut above, so the sentence cannot be read as a
recommendation. `market_flow.py` with no arguments prints the same notes under
the table for a one-off look at a game.

None of this is a model feature. Line movement is the market's own answer, so
feeding it to the model would cut the margin error while making
"does it beat the line" unanswerable by construction.

## 8. Totals: is the edge on over/unders instead?

Asked directly, after three flat tests on sides. Three separate tests, all on
the same data as above.

**The model against the closing total**, 1,943 out-of-sample games, `--report`:

| | value |
|---|---|
| O/U record taking the model's side | 50.3% |
| Blind under, same games | 51.1% |
| `total ~ total_line + (model − line)` disagreement coef | **+0.269, t=2.14** |

That t-stat is the first thing in this repo to clear 2, and it is still not a
bet. The coefficient says a 5-point disagreement with the total is worth
\(5 \times 0.269 \approx 1.3\) points of real scoring — against a 10.4-point
per-game error, which is why the record is a coin flip. It also does not
survive being split by season: +0.19, +0.15, +1.02, +0.23, +0.92, −0.27,
+0.56 across 2019–2025, so two years carry the pooled number and 2024 is
negative. Bucketing by edge size does not help either — 48.9% under a point,
49.9% over five.

**The market's own total movement** (`market_flow.py --study`, 1,360 aligned
games): backing a 0.5+ move covers 47.8%, 1+ covers 49.6%, 2+ covers 51.7%,
against a 50.7% blind-under base rate. Movement on totals is, if anything,
mildly contrarian, and none of it clears break-even.

**Week-1 unders**, `studies.py --totals`, 1999–2025:

| Cut | Under | n |
|---|---:|---:|
| Week 1 | 54.7% ±2.4 | 424 |
| Weeks 2+ | 50.2% ±0.6 | 6,444 |
| Week 1, 1999–2005 | 54.2% ±4.8 | 107 |
| Week 1, 2006–2015 | 53.8% ±4.0 | 158 |
| Week 1, 2016–2025 | 56.0% ±3.9 | 159 |

The effect is in the scoring, not just the ledger: week-1 games are posted at
43.4 and land at 42.9, while weeks 2+ are posted at 43.5 and land at 44.3. So
the market prices week 1 like a normal week and week 1 is about a point and a
half lighter. Consistent across all three eras, which is more than any other
cut here manages.

It is still not a bet, and the rolling ten-season window is why: 59.0% for
2001–2010, **45.6% for 2011–2020**, 56.0% for 2016–2025. A bettor starting in
2011 would have lost for a decade on the same "trend". 54.7% is 0.96 standard
errors above the 52.4% break-even — the same distance from noise as the
week-1 favorite result, and driven by the same 16-games-a-year sample.

**Answer to the question: no, the edge is not in totals either.** The
model knows slightly more about totals than about sides, and "slightly more"
is a quarter of a point.

## 9. `fantasyguru_pull.py` — the one paid feed

Fantasy Guru has no API. Their support (Rusty, 2026-09-12) wrote that
subscribers may feed the CSV/Excel downloads to a model, with one condition:

> If you tell it to rate limit the pulls, to say once a day or once an hour
> depending on the data you need, that is fine. If you need it to pull every 10
> minutes before lock or something that is fine too. It only becomes an issue
> when we have members who will hit it constantly.

So the interval is enforced in code, not in a habit: each dataset writes a
timestamp to `last_pull.json` and a run inside the window prints how long is
left and exits without touching the site.

```bash
export FANTASYGURU_USER=... FANTASYGURU_PASS=...   # never committed
python3 fantasyguru_pull.py                        # once a day, both sets
python3 fantasyguru_pull.py --dataset props --min-interval 600   # near lock
python3 fantasyguru_pull.py --force                # deliberate override
```

Downloads go to `~/fgdata/<set>/<date>/` — outside the repo, because it is a
paid feed and not ours to republish. The login session is cached in a persistent
browser profile there too, so repeat runs do not re-authenticate.

What is actually available, having walked all 88 subscriber pages:

| Set | Source | Rows | Worth |
|---|---|---|---|
| `props` | `/nfl-player-props` | ~1,150 across 13 markets | **The reason to do this.** Every prop priced at FanDuel, BetMGM, Caesars, Fanatics and a consensus — a cross-book comparison nflverse cannot produce |
| `rankings` | `/jeff-mans-nfl-weekly-rankings-ppr` | ~220 across 6 positions | Thin: rank, player, team, bye, opponent. No projection column |

The stat pages under `/data/nfl` — team stats, player stats, injuries, SMASH
reports — are Sportradar widgets with no export button and no underlying JSON of
our own to read, so there is nothing to pull there. That rules out the thing that
would have helped the game model most; what we got instead is a props feed.

Unverified so far: whether any of it improves a model. The props file is a
market snapshot, so its first use is measuring our own prop numbers against five
books at once, not adding a feature.

## 10. `input_check.py` — fact-check the inputs before publishing

Week 2 was published with Atlanta favoured by 5.1 on a schedule row that listed
Tua Tagovailoa as their starter. He had not practised all week. The arithmetic
was fine; the input was three days stale, and nothing in the build said so.

The model cannot read news — a feature has to be a number, and a number has to
be testable against past seasons before it earns a coefficient. What *can* be
automated is checking that the numbers it was handed still match reality:

```bash
python3 input_check.py --season 2026 --week 2
python3 input_check.py --season 2026 --week 2 --swap ATL="Cooper Rush"
```

Per slate it reports how old each feed is, how much of the injury report the
model is actually carrying, and for every announced starter whether the injury
report contradicts him, whether he differs from whoever took the snaps in that
team's last game, and whether he has enough career dropbacks to be rated at all.

Every flag comes with the number it is worth: the row is re-run with the most
likely replacement — the roster quarterback with the most career dropbacks who
is not ruled out — and both edges are printed. Week 2's two flags:

| Game | Assumed | Actually | Edge | If replaced |
|---|---|---|---:|---:|
| CAR @ ATL | Tua Tagovailoa | did not start week 1, no practice | +7.6 ATL | +5.7 (Cooper Rush) |
| MIN @ CHI | Kyler Murray | concussion protocol, Wentz started week 1 | +3.5 MIN | +2.5 (Carson Wentz) |

`picksheet_build.py` runs the check after writing the sheet and prints it, so a
stale input has to be read past rather than discovered afterwards. It writes
`picksheet/input_check.md` and **never edits a pick** — a published card is a
record, and the decision to revise one stays with a person.

What it deliberately does not do: score coaching changes, locker-room reports or
last week's headlines. There is no historical version of that text to test
against, so any weight put on it would be a guess wearing a model's clothes.

## 11. `notes_build.py` — the half of a game the model cannot hold

The model reads about 35 numbers and no sentences. It cannot know that Atlanta's
coach refused to name a quarterback, that Philadelphia's best interior lineman
sat out Wednesday, or that the Rams lost a pass rusher for a month. Turning that
into a feature would need a historical archive of the same text to test against,
which does not exist — so instead it lives beside the number, in a file written
by hand and labelled line by line:

```
## CAR @ ATL — Sun 10:00 AM PT
model: ATL by 5.1
line: CAR -2.5
pick: ATL +2.5 — DOUBLE
fact: Tua Tagovailoa did not practise Wednesday (oblique).
unknown: Stefanski will not name a starter.
read: The week's biggest edge rests on that unknown.
```

`fact` is published and checkable. `unknown` is written down so it cannot be
quietly promoted to a fact later. `read` is opinion and is labelled opinion — a
note with a `read` and no `fact` is the failure this format exists to prevent.

```bash
python3 notes_build.py notes/2026-w02.md --caption
# -> notes/2026-w02.html  (served at /notes)
# -> notes/2026-w02.txt   (the Instagram caption)
```

A game may also carry a `caption:` line — the same game in one sentence — and
`--caption` collects those between the header's `lead` and `tail` into the
post's text. It refuses to write a caption over 2,200 characters (Instagram
truncates) or one containing a link, because a caption cannot be clicked: the
page is reached through the profile link, so the caption only has to say so.
Week 2's caption is 1,524 characters across four games.

The renderer is a formatter, not a source of truth: it never touches the model,
the sheet, or a pick, and a `read` that disagrees with the pick stays in the
note rather than changing it. Week 2's notes carry 43 facts and 4 open
questions, and on three games — PHI @ TEN, WAS @ DAL, CLE @ TB — the reporting
argues against the model's own side. That is left visible on purpose.

The rendered page is uploaded as `notes.html` and served at `/notes`, linked
from the top of the week page. Missing notes answer with a page pointing back
at the numbers rather than with a 404 body, since a reader can arrive from that
link before the week's notes exist.

## 12. Offensive line: rating one lineman fails, counting absent starters works

The model docks a team the same amount for any missing non-quarterback, so a
left tackle and a fourth safety cost the same. The obvious repair is to rate
each lineman and adjust for him being in or out. Three scripts test whether
that rating can be built from public data, in the order the question has to be
asked.

```bash
python3 ol_study.py                       # unit level: continuity, position changes
python3 ol_player_study.py --shuffles 20  # player level: on/off vs a shuffled floor
python3 ol_player_check.py                # does the rating replicate?
python3 ol_player_check.py --player Kelce # one lineman's game log
python3 ol_missing.py --source injury     # what an absent starter costs
```

**What the free feed contains.** nflverse snap counts give per-game snap share
and a position for every lineman, but only as `T`, `G`, `C` — a left tackle
sliding to right tackle is invisible, and only about 1.5% of player-seasons
change even at that coarse level. Depth charts carry true `LT/LG/C/RG/RT` but
only from 2024. Play-by-play tags each run with a location and gap (end +0.096
EPA, guard −0.033, tackle −0.026 in 2024), which supports team-level scheme
work but does not say which lineman blocked whom.

**Unit level** (`ol_study.py`, 5,328 team-games). A settled five is worth about
+0.066 EPA per dropback over the most shuffled ones, roughly two points a game
— smaller than it feels. A lineman playing a different T/G/C spot shows **no
penalty at all**: sack rate 0.0660 moved against 0.0668 in place, and pass EPA
slightly better. The coarse position label is a plausible reason the effect
hides, so this is not proof the penalty is absent, only that it cannot be seen.

**Player level** (`ol_player_study.py`, 46,114 player-games, 499 linemen with
at least 8 starts and 4 misses). Each lineman is rated on his own team's
blocking with him in versus out, inside the same season and team, shrunk toward
zero by sample size. Reshuffling who started which games 20 times builds a
noise floor:

| | spread of ratings | shuffled | signal left |
|---|---|---|---|
| sack rate | 0.0073 | 0.0067 | 0.0029 |
| pass EPA | 0.0482 | 0.0427 | 0.0224 |
| rush EPA | 0.0294 | 0.0293 | 0.0021 |

Two clear the floor, and the surviving pass-EPA signal is 0.78 EPA over 35
dropbacks — under a point of margin for a one-sigma lineman. That is the
ceiling, and it is small.

**The rating does not replicate** (`ol_player_check.py`). Rating every lineman
twice on two random halves of his own games:

```
sack_rate  r = +0.014      pass_epa  r = -0.137      rush_epa  r = -0.189
```

Zero, and negative where it isn't. Season to season the carryover is the same
story: `+0.036`, `+0.089`, `+0.020`. Split the started games but leave the
missed games whole and correlation jumps to ~0.52 — both halves are then
subtracting the identical baseline, so that agreement is arithmetic, not skill,
and it is the trap this kind of table falls into.

The named list reads the same way: Jason Kelce and David DeCastro rate near the
top, which is right, while Dion Dawkins and Orlando Brown Jr. rate near the
bottom, which is not. **No lineman rating from this data enters the model.**

### But a missing starter does cost points — the market just knows

Rating one lineman fails. Counting how much of the usual five is absent does
not, and that is the question Jonathan actually asked. `ol_missing.py` marks a
lineman a starter walk-forward (at least half the snaps in 60% of his team's
last six games), then weights each absence by his own usual snap share, so a
never-leaves-the-field tackle costs a full unit and a rotational guard costs a
fraction. No opinion about who is good is required.

The catch is what "missing" means, and it changes the answer completely:

| `--source` | what it counts | margin | beyond the closing line |
|---|---|---:|---:|
| `snaps` | under half the snaps | +1.64 ± 0.30 | **+0.74 ± 0.27** |
| `inactive` | never dressed | +1.80 ± 0.36 | +0.56 ± 0.32 |
| `injury` | listed Out/Doubtful | +0.51 ± 0.55 | −0.03 ± 0.49 |

Points of home margin per one missing full-time starter on the away line, over
2,169 games. The first row looks like a market-beating edge and is not one: a
team being blown out pulls its starters, so "played under half the snaps"
is partly an effect of the result, and the regression reads it backwards. The
clean measures keep the football effect — a line missing a full-time starter
really is worth roughly 1.5 to 2 points — and lose the edge. Against the
closing line the only version the model could actually use on Friday scores
−0.03 ± 0.49: **the market prices missing linemen correctly.**

Blocking moves the way it should under the same measure: pass EPA −0.018 per
missing starter (t = −2.7) with three or more out costing −0.10, while sack
rate barely moves. One more caveat on the injury report row — it catches under
half of the absences the snap counts show (0.19 per game against 0.44), because
linemen are scratched without ever being designated Out.

Not yet tried, and the best free lead: nflverse
[participation data](https://nflreadr.nflverse.com/reference/load_participation.html)
lists every player on the field for every play back to 2016, free under
CC-BY-SA. That allows a play-level plus-minus instead of a game-level one, which
is a genuinely stronger estimator. It ships after the postseason, so it can
build ratings from past years but cannot see the current week.

Paid alternatives were checked rather than assumed. ESPN's pass block win rate
is real — tracking chips, a 2.5-second survival threshold — but is published as
a weekly top-20 list inside articles, with no per-game history to backtest.
Pancakes are not an NFL statistic and never have been; they are hand-charted by
teams and schools. [Sports Info
Solutions](https://www.sportsinfosolutions.com/football/) is the serious one:
every play charted since 2015, per-lineman blown-block rate and blocking Total
Points, downloadable as CSV, with the free tier capped at top-20 leaderboards
and full access at $749.99/year. Worth revisiting only if an OL feature first
shows value.

## Data sources

- Fantasy Guru subscriber pages (paid, permission on file) — cross-book player
  prop lines and weekly fantasy rankings.
- [nflverse games.csv](http://www.habitatring.com/games.csv) — results plus
  closing spread/total/moneyline, 1999–present.
- [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases) —
  play-by-play, rosters, injuries, weekly player stats, through 2026.
- [Sportsbook Review consensus](https://www.sportsbookreview.com/betting-odds/nfl-football/consensus/)
  — public ticket percentages and per-book timestamped line history, served as
  JSON in the page payload. Percentages exist from 2021 on, patchily in 2023;
  line history reaches back to 2019.
- Kalshi public trade API — live books.

## Standing caveat

Backtested and modelled results do not demonstrate future profitability. Nothing
here places orders.
