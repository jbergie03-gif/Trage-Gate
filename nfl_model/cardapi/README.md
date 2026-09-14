# cardapi

Serves the ATS pick sheet (`../picksheet/index.html`) and collects the cards
submitted from it, so a card arrives with a Pacific timestamp instead of being
pasted into chat.

Stdlib only — no packages to install and nothing to break before kickoff.

Two properties are deliberate:

- **Append-only.** Resubmitting files a new revision rather than overwriting,
  which is what makes "the pick was in before kickoff" checkable rather than
  asserted. Amending a pick on late injury news stays legitimate *and* visible.
- **Same origin.** The sheet is served by this process rather than from a
  separate static host, because a page loaded over HTTPS cannot POST to an HTTP
  endpoint. Serving both together removes the copy/paste step without needing a
  certificate for a bare IP.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | The pick sheet |
| POST | `/card` | Submit: `{slate, who, picks:[{game, side, double}]}` |
| GET | `/latest?slate=&who=` | The card that stands, plus a revision count |
| GET | `/cards?slate=&who=` | Full submission history |
| GET | `/health` | Liveness, card count, active subscriber count |
| GET | `/week` | The weekly model-vs-market page |
| POST | `/subscribe` | Email signup: JSON or form `{email, source}` |
| GET | `/unsubscribe?e=&t=` | One-click opt-out from an email footer |
| GET | `/subscribers` | Active list, requires `X-Admin-Token` |

Cards are JSON lines in `$CARD_DATA_DIR/cards.jsonl`.

## Subscribers

`$CARD_DATA_DIR/subscribers.jsonl`, append-only like the cards: signups,
unsubscribes and resubscribes are all events, and the last event for an address
is its current state. Nothing is ever deleted, so "they asked to be removed and
we kept mailing them" is answerable from the file.

Unsubscribe links carry an HMAC of the address keyed by
`$CARD_DATA_DIR/subscriber_secret` (created `0600` on first use). Links keep
working across restarts and redeploys because the key is on disk rather than in
memory — a dead unsubscribe link is a CAN-SPAM problem, not an inconvenience.

`/subscribers` returns 503 until `ADMIN_TOKEN` is set in the unit's
environment, so the list cannot be read by default. Set it out of band:

```bash
ssh root@<host> 'systemctl edit --force nfl-cards'   # Environment=ADMIN_TOKEN=...
```

Signups are rate limited to 20 per hour per IP. The endpoint is public, so
treat the list as unverified addresses — there is no confirmation email yet.

## Run locally

```bash
PORT=8899 CARD_DATA_DIR=/tmp/cards PICKSHEET=../picksheet/index.html python3 server.py
```

## Deploy

Runs on the same droplet as `nfl_scanner`, on port 80:

```bash
scp server.py ../picksheet/index.html root@<host>:/opt/nfl-cards/
scp nfl-cards.service root@<host>:/etc/systemd/system/
ssh root@<host> 'systemctl daemon-reload && systemctl enable --now nfl-cards'
```

Plain HTTP on a bare IP. That was fine when the box held only spreads and
pick'em selections; it now takes email addresses, which means **signups travel
unencrypted**. A domain with TLS should land before the page is advertised
anywhere. No credentials are stored either way.

## Publishing the week page

`weekly_post.py` writes the page; the droplet only serves it. Fitting the model
peaks around 520 MB and the box has 458 MB, so generation stays off it:

```bash
python3 ../weekly_post.py --out /tmp/week.html
scp /tmp/week.html root@<host>:/opt/nfl-cards/week.html
```

No restart needed — the file is read per request. Served at `/week`.

The same command also writes `/tmp/week.png`, the 1080x1350 Instagram frame,
and `/tmp/week_post.html` that it is rendered from. The image is a separate
dense layout rather than a screenshot of the page: a 16-game slate does not fit
in a 4:5 frame one card at a time. `--no-image` skips it.

## Publishing the pick sheet

Same idea: `../picksheet_build.py` generates `../picksheet/index.html` from
`../picksheet/template.html`, the schedule and the latest DraftKings snapshot,
then the file is copied up. It builds **every** game of the week — the sheet was
hand-written for week 1 and the Thursday, Sunday-night and Monday-night games
were left off it, so three games could not be picked at all.

```bash
python3 ../picksheet_build.py            # current week, or --season/--week
scp ../picksheet/index.html root@<host>:/opt/nfl-cards/
```

A game whose kickoff has passed renders locked, and a game the book has not
priced yet renders as "no line yet" instead of being dropped. Rerun once the
line posts.

Changes to `server.py` do need a restart:

```bash
scp server.py root@<host>:/opt/nfl-cards/ && ssh root@<host> 'systemctl restart nfl-cards'
```
