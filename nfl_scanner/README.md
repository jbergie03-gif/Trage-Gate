# Cross-venue NFL prediction market scanner

Logs NFL moneyline order books from **Kalshi** and **Polymarket** on a schedule and
records every cross-venue price gap, net of each venue's fees.

It exists to answer one question with data instead of opinion: **do exploitable price
gaps between prediction-market venues actually open during an NFL week?** A one-day
snapshot said no (0 of 19 games had a profitable two-sided basket; the single crossed
book was 1c gross on 11 contracts, which fees erase). That is one moment in time, so
this collects the whole season instead.

It is read-only. It has no trading code, no API keys, and no ability to place an order.

## What it records

| Table | Contents |
|---|---|
| `quotes` | Every best bid/ask with depth, per team, per venue, per snapshot |
| `gaps` | Every cross-venue gap found, with gross edge, executable size, and net P/L after fees |
| `runs` | One row per pass, including errors — so missed polls are visible, not silent |

Two kinds of gap are measured:

- **`same_outcome`** — one venue's ask is below the other venue's bid for the same team.
  Buy there, sell here, close immediately.
- **`two_sided`** — the two teams' asks sum to under $1.00 across venues. Since exactly
  one side settles at $1.00, buying both is a locked payout *if* cost plus fees stays
  under $1.00.

## Fees

Taken from primary sources, applied before anything is called profitable:

| Venue | Taker fee | Per 100 contracts at $0.50 |
|---|---|---|
| Kalshi | `ceil(0.07 * C * P * (1-P))` | $1.75 |
| Polymarket (sports) | `0.05 * C * 2 * P * (1-P)` | $1.25 |
| DraftKings Predictions | tiered table, **per side** ($0.02/contract at $0.30–$0.94) | $2.00, and again to close |

Makers pay nothing on Kalshi or Polymarket.

## DraftKings is not included

DraftKings Predictions returns HTTP 403 to automated requests and only renders in a
browser, so it cannot be polled. It stays a manual spot-check. Not a large loss for the
research question: on the slate checked by hand, DK was priced 1–5c *worse* than Kalshi on
every side (e.g. BUF/HOU 54+49=103 vs Kalshi 52+48=100), so no gap involving DK favored
buying there.

## Schedule

Polling is dense only when prices move — news and live play — and idle otherwise.
All times Pacific.

| Window | Every |
|---|---|
| Sun 7–10 AM (inactive reports) | 60s |
| Sun 10 AM–9 PM (live games) | 30s |
| Thu & Mon 5–9 PM (TNF/MNF) | 30s |
| Sat 10 AM–9 PM | 120s |
| Other daytime | 30 min |
| Overnight | 60 min |

## Usage

```bash
python3 scan.py --once     # single pass, prints a summary line
python3 scan.py            # run forever on the adaptive schedule
python3 report.py          # what has been found so far
python3 report.py --hours 24
```

Standard library only — no pip install, no virtualenv needed.

## Deploy

### HexOS / TrueNAS SCALE (free, uses hardware you already own)

In the TrueNAS UI: **Apps → Discover Apps → ⋮ → Install via YAML**, paste
[`hexos-compose.yaml`](hexos-compose.yaml), and change the volume's left-hand path to a
real dataset on your pool (e.g. `/mnt/tank/apps/nfl-scanner`).

Nothing to build. The container runs `python:3.12-slim` and downloads these scripts from
this repo's `main` branch on every start, so restarting it is also how you update it. The
SQLite database lives on the mounted dataset, which means it survives restarts, updates,
and container deletion — and gets covered by your ZFS snapshots.

```bash
docker exec nfl-scanner python /app/report.py      # what it has found so far
docker logs -f nfl-scanner                         # live; ALERT lines matter
```

Caveat: a home NAS is on your power and your ISP. A Sunday outage costs exactly the data
this is collecting. Fine for answering "do gaps exist"; not what you'd trade from.

### Ubuntu VPS

```bash
git clone --depth 1 https://github.com/jbergie03-gif/Trage-Gate.git /tmp/tg
sudo bash /tmp/tg/nfl_scanner/install.sh
```

Installs to `/opt/nfl-scanner`, runs as an unprivileged `scanner` user under systemd,
restarts on failure, starts on boot.

```bash
journalctl -u nfl-scanner -f    # live; ALERT lines are the ones worth reading
```

An `ALERT` is logged only when a gap is at least 2c gross **and** at least 100 contracts
deep — wide enough to survive fees and big enough to be worth acting on.

## Reading the results honestly

- Everything here is observed past prices. It is not evidence that a future gap is
  capturable: by the time a poll sees a crossed book, a faster participant may already
  have taken it.
- A logged `net_dollars` above zero is a *modeled* fill at the top-of-book price and size.
  Real execution adds slippage, partial fills, and the risk of getting one leg filled and
  not the other — which converts a "locked" trade into an open directional bet.
- No live trading should follow from this data without out-of-sample forward testing and
  a hard position limit.
