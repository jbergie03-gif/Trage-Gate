# Input check — 2026 week 3
_run 2026-09-23 22:18 PT_

## Feed freshness

- schedule + announced starters: 0h old
- injury report: 0h old
- injury burden the model uses: 269h old

- injury report rows for week 3: **22**, of which **0** carry an Out/Doubtful/Questionable designation
- **the model is pricing all 32 teams as fully healthy.** Designations are not published until Friday, so its three injury features are zero for every game on this slate.

## Quarterbacks the model is assuming

| Game | Team | Model assumes | Problem |
|---|---|---|---|
| ATL @ GB | ATL | **Michael Penix Jr.** | injury report says **knee**; did not start week 2 — C.Rush did |
| MIN @ TB | MIN | **Kyler Murray** | did not start week 2 — C.Wentz did |
| PHI @ CHI | CHI | **Case Keenum** | did not start week 2 — C.Williams did |

## What the flags are worth

Each row re-runs the model with the most likely replacement (most career dropbacks on the roster who is not ruled out) and shows how far the pick moves. A published card is **not** changed by this.

| Game | If instead | Model now | Model then | Line | Edge now | Edge then |
|---|---|---|---:|---:|---:|---:|
| ATL @ GB | Tua Tagovailoa (2568 career dropbacks) | +6.2 | +5.8 | +4.5 | -1.7 | -1.3 |
| MIN @ TB | Carson Wentz (3806 career dropbacks) | -1.9 | -1.0 | -1.5 | +0.4 | -0.5 |
| PHI @ CHI | Caleb Williams (1382 career dropbacks) | +1.9 | +2.8 | -4.5 | +6.4 | +7.3 |

Margins are the home team's. Edges are signed for the team in the flagged column, so a shrinking edge means the model likes that side less.

## What this cannot check

- Coaching, scheme and locker-room news. None of it is a number in the feed, and there is no historical version of it to test against, so it stays out of the model rather than being guessed at.
- Whether a Questionable player actually plays. That is Sunday morning information.
- Weather. The model reads a game-time observation historically and a blank for an upcoming game, which is its own known gap.

