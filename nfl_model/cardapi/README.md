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
| GET | `/health` | Liveness and card count |

Cards are JSON lines in `$CARD_DATA_DIR/cards.jsonl`.

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

Plain HTTP, so treat everything it holds as public. It holds spreads and pick'em
selections and nothing else — no credentials and no personal data.
