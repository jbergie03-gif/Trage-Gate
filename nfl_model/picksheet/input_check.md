# Input check — 2026 week 8
_run 2026-10-28 11:25 PT_

## Feed freshness

- schedule + announced starters: 0h old
- injury report: 0h old
- injury burden the model uses: 0h old

- injury report rows for week 8: **16**, of which **0** carry an Out/Doubtful/Questionable designation
- **the model is pricing all 32 teams as fully healthy.** Designations are not published until Friday, so its three injury features are zero for every game on this slate.
- teams carrying an injury burden in week 8: **0** (file built through week 7)

## Quarterbacks the model is assuming

| Game | Team | Model assumes | Problem |
|---|---|---|---|
| PHI @ WAS | PHI | Tanner McKee | only 171 career dropbacks, so the model discounts his rating |
| CAR @ GB | CAR | Bryce Young | injury report says **knee** |

## What this cannot check

- Coaching, scheme and locker-room news. None of it is a number in the feed, and there is no historical version of it to test against, so it stays out of the model rather than being guessed at.
- Whether a Questionable player actually plays. That is Sunday morning information.
- Weather. The model reads a game-time observation historically and a blank for an upcoming game, which is its own known gap.

