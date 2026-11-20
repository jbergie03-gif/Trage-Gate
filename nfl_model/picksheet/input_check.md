# Input check — 2026 week 11
_run 2026-11-19 17:18 PT_

## Feed freshness

- schedule + announced starters: 0h old
- injury report: 0h old
- injury burden the model uses: 0h old

- injury report rows for week 11: **253**, of which **15** carry an Out/Doubtful/Questionable designation
- teams carrying an injury burden in week 11: **2** (file built through week 11)

## Quarterbacks the model is assuming

| Game | Team | Model assumes | Problem |
|---|---|---|---|
| BAL @ CAR | BAL | **Tyler Huntley** | did not start week 10 — J.Brissett did |
| ARI @ KC | ARI | **Gardner Minshew** | did not start week 10 — C.Beck did |
| NYJ @ LAC | NYJ | **Geno Smith** | injury report says **limited in practice, ankle**; did not start week 10 — C.Klubnik did |
| MIA @ BUF | MIA | Kyle McCord | only 36 career dropbacks, so the model discounts his rating |
| TB @ DET | TB | Baker Mayfield | injury report says **did not practice, foot** |
| LV @ DEN | LV | Fernando Mendoza | only 35 career dropbacks, so the model discounts his rating |
| PIT @ PHI | PHI | Joe Milton III | only 82 career dropbacks, so the model discounts his rating |
| BAL @ CAR | CAR | Bryce Young | injury report says **foot** |
| ARI @ KC | KC | Patrick Mahomes | injury report says **elbow** |

## What the flags are worth

Each row re-runs the model with the most likely replacement (most career dropbacks on the roster who is not ruled out) and shows how far the pick moves. A published card is **not** changed by this.

| Game | If instead | Model now | Model then | Line | Edge now | Edge then |
|---|---|---|---:|---:|---:|---:|
| BAL @ CAR | Lamar Jackson (3446 career dropbacks) | +2.7 | +0.7 | +3.0 | +0.3 | +2.3 |
| ARI @ KC | Carson Palmer (929 career dropbacks) | +12.2 | +11.6 | +16.5 | +4.3 | +4.9 |
| NYJ @ LAC | Will Levis (602 career dropbacks) | +0.3 | +0.5 | +3.0 | +2.7 | +2.5 |

Margins are the home team's. Edges are signed for the team in the flagged column, so a shrinking edge means the model likes that side less.

## Asked what-if

- BAL @ CAR with Jacoby Brissett at BAL: home margin +2.7 → **+3.3** against a line of +3.0

## Asked what-if

- ARI @ KC with Carson Beck at ARI: home margin +12.2 → **+14.7** against a line of +16.5

## What this cannot check

- Coaching, scheme and locker-room news. None of it is a number in the feed, and there is no historical version of it to test against, so it stays out of the model rather than being guessed at.
- Whether a Questionable player actually plays. That is Sunday morning information.
- Weather. The model reads a game-time observation historically and a blank for an upcoming game, which is its own known gap.

