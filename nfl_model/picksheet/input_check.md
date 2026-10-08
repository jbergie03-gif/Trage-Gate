# Input check — 2026 week 5
_run 2026-10-08 15:57 PT_

## Feed freshness

- schedule + announced starters: 0h old
- injury report: 0h old
- injury burden the model uses: 0h old

- injury report rows for week 5: **222**, of which **9** carry an Out/Doubtful/Questionable designation
- teams carrying an injury burden in week 5: **2** (file built through week 5)

## Quarterbacks the model is assuming

| Game | Team | Model assumes | Problem |
|---|---|---|---|
| NYG @ WAS | WAS | **Jayden Daniels** | injury report says **elbow**; did not start week 4 — A.Kaliakmanis did |
| SF @ SEA | SEA | **Drew Lock** | did not start week 4 — S.Darnold did |
| TB @ DAL | TB | Jalon Daniels | only 30 career dropbacks, so the model discounts his rating |
| CHI @ GB | CHI | Tyson Bagent | only 184 career dropbacks, so the model discounts his rating |
| BAL @ ATL | BAL | Lamar Jackson | injury report says **did not practice, ankle** |
| LV @ NE | NE | Drake Maye | injury report says **shoulder** |
| MIN @ NO | NO | Tyler Shough | injury report says **limited in practice, hand** |

## What the flags are worth

Each row re-runs the model with the most likely replacement (most career dropbacks on the roster who is not ruled out) and shows how far the pick moves. A published card is **not** changed by this.

| Game | If instead | Model now | Model then | Line | Edge now | Edge then |
|---|---|---|---:|---:|---:|---:|
| NYG @ WAS | Marcus Mariota (2223 career dropbacks) | +3.6 | +3.7 | +3.5 | +0.1 | +0.2 |
| SF @ SEA | Sam Darnold (3246 career dropbacks) | +0.5 | +0.9 | +3.0 | -2.5 | -2.1 |

Margins are the home team's. Edges are signed for the team in the flagged column, so a shrinking edge means the model likes that side less.

## What this cannot check

- Coaching, scheme and locker-room news. None of it is a number in the feed, and there is no historical version of it to test against, so it stays out of the model rather than being guessed at.
- Whether a Questionable player actually plays. That is Sunday morning information.
- Weather. The model reads a game-time observation historically and a blank for an upcoming game, which is its own known gap.

