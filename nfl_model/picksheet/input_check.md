# Input check — 2026 week 4
_run 2026-10-01 16:22 PT_

## Feed freshness

- schedule + announced starters: 0h old
- injury report: 0h old
- injury burden the model uses: 0h old

- injury report rows for week 4: **257**, of which **2** carry an Out/Doubtful/Questionable designation
- teams carrying an injury burden in week 4: **1** (file built through week 4)

## Quarterbacks the model is assuming

| Game | Team | Model assumes | Problem |
|---|---|---|---|
| IND @ WAS | WAS | **Jayden Daniels** | injury report says **limited in practice, elbow**; did not start week 3 — M.Mariota did |
| GB @ TB | TB | **Jalon Daniels** | did not start week 3 — B.Mayfield did; only 0 career dropbacks, so the model discounts his rating |
| LAC @ SEA | SEA | **Drew Lock** | did not start week 3 — S.Darnold did |
| TEN @ BAL | BAL | Lamar Jackson | injury report says **limited in practice, back** |
| NE @ BUF | NE | Drake Maye | injury report says **shoulder** |
| KC @ LV | KC | Patrick Mahomes | injury report says **knee** |
| DET @ CAR | CAR | Bryce Young | injury report says **knee** |

## What the flags are worth

Each row re-runs the model with the most likely replacement (most career dropbacks on the roster who is not ruled out) and shows how far the pick moves. A published card is **not** changed by this.

| Game | If instead | Model now | Model then | Line | Edge now | Edge then |
|---|---|---|---:|---:|---:|---:|
| IND @ WAS | Marcus Mariota (2223 career dropbacks) | +0.8 | +1.0 | -3.5 | +4.3 | +4.5 |
| GB @ TB | Tom Brady (5190 career dropbacks) | -2.9 | -1.0 | -3.5 | +0.6 | +2.5 |
| LAC @ SEA | Sam Darnold (3221 career dropbacks) | +9.7 | +10.3 | +7.0 | +2.7 | +3.3 |

Margins are the home team's. Edges are signed for the team in the flagged column, so a shrinking edge means the model likes that side less.

## What this cannot check

- Coaching, scheme and locker-room news. None of it is a number in the feed, and there is no historical version of it to test against, so it stays out of the model rather than being guessed at.
- Whether a Questionable player actually plays. That is Sunday morning information.
- Weather. The model reads a game-time observation historically and a blank for an upcoming game, which is its own known gap.

