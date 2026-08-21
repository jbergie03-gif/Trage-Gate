# Trade Gate

A local discipline gate and journal for Apex EOD accounts (MES/ES). It sizes the trade,
refuses the ones your rules forbid, tracks payout progress, and keeps the journal.

**It never places an order.** Apex prohibits automation and algorithmic execution, so there is
no broker connection, no Apex login, and no credentials anywhere in this project. You place
every fill by hand, matching the ticket the app prints.

## Run it

```bash
cd trade_gate
.venv/bin/python app.py          # or: python3 -m venv .venv && .venv/bin/pip install flask reportlab
```

Open <http://127.0.0.1:8765>. Everything is local: rules in `config.json`, journal in
`journal.db` (SQLite, created on first run).

## The day

1. Open the gate before the platform. It shows your risk, remaining loss budget, buffer to the
   EOD threshold, and whether the session is open.
2. Enter direction, entry, stop, target → **CALCULATE SIZE**. You get contracts, exact dollar
   risk, the net result if it wins or loses, and whether a win makes today a qualifying day.
3. **CONFIRM & LOG** records the ticket. Place it in your platform yourself.
4. Record the exit. P&L is stored net of commissions, because Apex judges a qualifying day on
   net profit.
5. The gate closes for the day on: target hit, daily stop, two consecutive losses, three
   trades, or the end of the session window. It reopens at the daily reset (6:00 PM ET = 3:00 PM PT).

**Every time you read is Pacific.** The session is 6:30–9:30 AM PT with a hard flat at
12:55 PM PT. The rules are stored in exchange time (Chicago) in `config.json` because the
opening bell is an exchange event, and converted to PT for display; any other zone is labelled
where it appears.

Blocked and want through anyway? Overrides need a written reason of 15+ characters and are
recorded permanently on the journal.

## Files

| File | What it is |
|---|---|
| `config.json` | Every rule and account parameter. Apex-verified values and your personal rules are labelled separately. Edit before a session, never during. |
| `rules.py` | The engine: sizing, lockouts, EOD threshold, payout eligibility, consistency. |
| `app.py` | Flask API + the dashboard route. |
| `templates/index.html` | The dashboard. |
| `test_rules.py` | 185 engine checks. `.venv/bin/python test_rules.py` |
| `test_api.py` | Drives the live HTTP API end to end. Start the server first. |
| `build_rulebook.py` | Regenerates `Trade_Gate_Rulebook.pdf` from `config.json`. |
| `chart.py` | Draws the candlestick chart of a session's trades that the report embeds. |
| `journal.db` | Your trades, overrides and payout records. **This is the file to back up.** |

## Adjusting the rules

All of it lives in `my_rules` in `config.json` — risk percentage, daily stop, trade cap,
cooldown, session window, stop width, minimum reward:risk, daily target buffer.

Two values you should set to your real numbers:

- `instruments.*.commission_round_trip` — currently estimates ($1.24 MES, $3.10 ES round trip
  per contract). Qualifying days depend on net profit, so these matter.
- `mae.enforce` — false. Apex's 30% MAE rule is labelled Legacy with no EOD equivalent page.
  Set it to true only if Apex support confirms it applies to EOD PAs.

Adding an account size (e.g. 250K) needs its verified profit target, EOD drawdown, daily loss
limit, max ES contracts, minimum daily profit, safety net, minimum balance to request, and the
six payout caps. Don't guess them.

## Testing the strategy (not just the rules)

The app enforces risk. It says nothing about whether your entries make money. These four
files answer that separately.

| File | What it does |
|---|---|
| `simulate.py` | Monte Carlo over 4,000 simulated accounts per scenario. Takes an edge as an assumption and compares behaviour patterns: the gate vs. no target lock vs. holding for a bigger day vs. revenge sizing vs. overtrading. Shows what share of accounts get paid and what share hit the EOD threshold. |
| `backtest_orb.py` | Pilot backtest of the opening range break on ES 1-minute data, sweeping 1/2/3/5-minute range lengths against four mechanical exits, and reporting how often each range length even fits the 2–12 point stop rule. Small sample by design — free intraday futures history is capped at ~30 days. |
| `orb.pine` | The opening range break for TradingView's Strategy Tester, with the gate's rules built in and the exit as a dropdown. This is the real backtest: your account has years of MES minute data. |
| `fib_pullback.pine` | The .618/.786 pullback, with the swing leg defined by pivots so it can actually be tested. |
| `lab/deep_history.py` | Years of 1-minute S&P 500 bars from Dukascopy's open tick archive — no account, no key. Its `USA500IDXUSD` is the cash index CFD, not ES: absolute prices sit a basis below the future, but the opening-range widths match to about half a point, so R-based results carry over. This is what lifts the lab studies past the free feed's ~30-day wall. |
| `lab/orb_reentry.py` | Measures the second ORB trade in the same direction after the first one stops out — trigger, cooldown, target and range length all swept, so the answer can be checked for robustness instead of read off one setting. Findings in `lab/ORB_REENTRY.md`. |
| `replay.py` | Runs *your own* trade history through the gate. Two passes: what happened, and what would have happened with the daily locks applied. Reads Tradovate report exports, the Apex trade log, or TradingView's "List of Trades" CSV. |

```bash
.venv/bin/python simulate.py
.venv/bin/python backtest_orb.py
.venv/bin/python replay.py ~/Downloads/my_fills.csv --account 100K
.venv/bin/python lab/deep_history.py --years 2          # -> data/SP500_1min_deep.csv
.venv/bin/python lab/orb_reentry.py --csv data/SP500_1min_deep.csv
```

### The paper engine, and the report it writes each session

`paper_engine.py` runs the setup mechanically so the rules can be watched working without
anyone clicking anything. It reads price bars, builds the opening range, takes the break,
sizes through the same engine the dashboard uses, and fills against the bar data. It holds no
credentials, reaches no broker and cannot place an order.

```bash
# needs: flask pandas yfinance reportlab matplotlib
.venv/bin/python paper_engine.py --live                       # delayed 1-minute feed
.venv/bin/python paper_engine.py --replay es_1m.csv --speed 0 # a month of sessions in seconds
.venv/bin/python paper_engine.py --replay es_1m.csv --live-view --speed 0.02
.venv/bin/python paper_engine.py --replay es_1m.csv --setups orb        # ORB alone
.venv/bin/python paper_engine.py --replay es_1m.csv --setups fib --pivot-len 5
```

Both setups run by default and share one day: the opening range break is taken once, at the
bell, and the Fib pullback is looked at afterwards only while flat — so the trade count, the
cooldown and every daily lock apply to the pair, not to each setup separately.

The Fib leg is defined by pivots (`--pivot-len` bars each side, `--min-leg` points), entry on
a close back out of the .618 zone, stop beyond the leg origin. Change the pivot length and the
results move a long way; that sensitivity is itself the finding.

Paper trades are written to `paper_journal.db`, never to the real journal — that separation is
the `TRADE_GATE_DB` environment variable, which the engine sets for itself.

With `--live` or `--live-view`, **http://127.0.0.1:8765/paper** shows the opening range, any
open position, the day's P&L against the locks, and a running log of what the engine did and
refused to do.

At the close of every session it writes `reports/session-YYYY-MM-DD.md`: every trade with its
entry, stop, exit, R and net P&L; the setups the rules refused and why; which rule ended the
day; whether the day cleared Apex's $300 net minimum; and the running count of qualifying days
and profit still needed for a payout. `reports/summary.md` stacks every session into one table.

Alongside it goes `reports/chart-YYYY-MM-DD.png`: the session on Pacific time with the opening
range, each entry (triangle), each exit (cross), the stop that was working while the trade was
on (dashed), and the trade's net P&L and R. Drawn by `chart.py`, which needs `matplotlib` —
without it the report is written as before, just without the picture. Bars outside
06:15–13:05 PT are left out so the trading day fills the frame.

The engine trades the 1-minute bars; the chart aggregates them into **3-minute candles**, to
match the opening candle the ORB rule is measured on. `--chart-minutes` changes the candle
size (`--chart-minutes 1` for the raw bars) and never changes a trade — the markers sit on the
exact minute either way.

The exit rule is a flag, and it changes everything:

| `--exit` | what it does |
|---|---|
| `opposite_end` | hold until price breaks the other end of the range — your original description |
| `fixed_2R` / `fixed_1.5R` | fixed multiple of the stop |
| `scale_2R` | most of the position off at 2R, the rest left as a runner on a breakeven stop that trails 1R behind the high — `--runner-pct` sets the share |
| `trail_after_1R` | trail by 1R once 1R in profit |
| `session_end` | flat at the end of the session window |
| `day_target` | size the target to finish a qualifying day in one trade, then stop |

`day_target` exists because of an arithmetic problem worth knowing: **a flat 2R cannot make a
qualifying day.** $150 of risk doubled is $300 gross, and Apex's $300 minimum is net, so
commissions leave it a few dollars short. A qualifying day needs about 2.17R, two winners, or
a wider target.

`scale_2R` is the attempt to have both: bank the trade at 2R, keep a runner for the trend day.
Two things about it are worth knowing before trusting it. Runners are **whole contracts** — 10%
of a 4-contract position is not a contract, so the runner rounds up to one and the core keeps
one; below two contracts nothing splits and it behaves as `fixed_2R`. And on the pilot's 20 ORB
sessions it lands between the two extremes rather than beating them:

| exit | net | qualifying days |
|---|---|---|
| `opposite_end` | +$1,070 | 4 |
| `scale_2R` (10% runner) | +$79 | 2 |
| `fixed_2R` | -$258 | 0 |

Same 16 trades, same 5 winners. Scaling out rescues most of what the flat 2R gives away, but on
this sample the money was in the few big trend days, and taking 3 of 4 contracts off at 2R is
exactly what cuts those short. One month of one regime — not a verdict, but not encouraging
either.

### Re-entry, and why the stop is the weak point

`--orb-reentry` allows exactly one re-entry after a stop-out: same direction, when price closes
back through the level, still inside every daily lock. It exists because of a real session —
14 Aug 2026, where the short was correct (ES fell 25 points by midday) and lost anyway, because
the stop at the opposite end of a 6.75-point range was poked by half a point first. With the
re-entry that day goes from -$140 to +$145.

`--stop-buffer` widens the stop by N points instead. It does not work: the range gets poked
either way, and the wider stop just buys fewer contracts and loses more per trade (-$1,061 at a
2-point buffer). Across the 20 replay sessions the re-entry is close to noise (+$322 vs +$289),
which is the honest reading — it rescued one day badly, and one day is not evidence.

Because none of this is settled, the daily run keeps a **shadow**: the same session is replayed
under the original hold-to-the-opposite-end rule into `reports/shadow/` and its own journal, so
the week produces a comparison instead of a single path.

### Comparing timeframes without fooling yourself

Both setups reportedly worked best on a 2-minute chart, so that is where to start — but two
things make a naive comparison meaningless:

- **The opening range and the chart are separate choices.** A 2-minute chart with a
  3-minute range is not the same test as a 2-minute range. Set `Opening range length` to what
  you actually mean, and run the script on a 1-minute chart if you want the range to be exact
  (on a 2-minute chart the range rounds up to whole bars).
- **The Fib pivot length is measured in bars, not minutes.** A 10-bar pivot spans 20 minutes
  on a 2-minute chart and 10 on a 1-minute chart. Halve the pivot length when you double the
  bar size if you want the leg definition held constant.

With two setups, four exits, four range lengths and several pivot lengths there are dozens of
combinations, so one will look excellent by luck. Choose the settings on the older half of the
history, then run the winner on the recent half **without changing anything**. If it does not
hold up, it was a curve fit.

### Alerts: the ticket on your phone, placed by your hand

Both Pine scripts fire `alert()` calls. The entry alert is the whole ticket — side, contracts
sized to your $150 risk, entry, stop, target and the dollar risk and reward — so there is
nothing to calculate while the level is being tested. They also fire:

- **DONE FOR THE DAY** when a lock trips, naming which one. This is the message that arrives
  at the exact moment you would otherwise talk yourself into one more trade.
- **FLATTEN NOW** at the hard flat time, because holding through the close forfeits the account.
- **SKIP** when the opening range is too wide to trade under the stop rule, so a no-trade day
  registers as a decision rather than an absence.

Create the alert with Condition set to the script, and **leave the webhook URL field empty.**
An empty webhook is the whole compliance distinction: notifications go to you, orders come
from you. Alerts evaluate on bar close, so on a 2-minute chart the ticket can arrive up to two
minutes after the break prints.

Webhook bridges (PickMyTrade, TradersPost and similar) route these alerts straight to
Tradovate. Their marketing says Apex permits it; Apex's Prohibited Activities page says "No
Automation or Algorithm Usage allowed." Do not resolve that contradiction with a vendor's
opinion — the penalty is the account and its balance.

Also worth knowing: there is no TradingView API key for a trader to obtain, and Tradovate's
help centre states that "prop firm and evaluation accounts are not eligible for API access."
Data moves by CSV export in both directions. See `tradingview_api_findings.md`.

### The Pine scripts must never be connected to a broker

TradingView can auto-execute a strategy through a linked Tradovate account. On an Apex
account that is algorithmic execution — Apex's Prohibited Activities page forfeits the
account and its balance for it. Load these in the Strategy Tester, read the numbers, and
place every live order by hand. Check the chart's account selector before each session so a
manual order can't land on the funded account by accident.

### What the simulation actually showed

With a genuine edge, the daily locks *cost* speed — an undisciplined trader with a real edge
reaches a payout faster. With a marginal edge they are the difference between roughly half of
accounts getting paid and none. With no edge, nothing works: no ruleset makes an edgeless
trader profitable, it only changes how quickly the account dies. So the rules are insurance,
not an edge, and the backtests above are what determine whether an edge exists at all.

## Not financial advice

Trade Gate does not predict markets, does not guarantee a payout, and cannot stop you from
overriding it. Apex accounts are simulated; payouts are discretionary and subject to Apex's
eligibility and compliance review.
