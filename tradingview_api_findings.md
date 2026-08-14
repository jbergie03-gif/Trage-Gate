# Can we get a TradingView API key? — what I found

Checked 2026-08-14 against primary sources (TradingView's own docs and Tradovate's help
center), not vendor marketing.

## Short answer

There is no public TradingView API key for a retail user. Nothing you can sign up for gives
your code programmatic access to your TradingView account, your charts, or their data feed.
The tools you have seen are using **webhook alerts**, which need no key at all.

## What TradingView actually offers

| Surface | What it is | Available to you? |
|---|---|---|
| **Webhook alerts** | When an alert fires, TradingView sends an HTTP POST to a URL you choose, with your alert message as the body. Official and documented. | **Yes**, no key needed. Requires a paid plan for webhook alerts. |
| **REST API for Brokers** (`tradingview.com/broker-api-docs`, `/rest-api-spec`) | Inverted from what you would expect: the *broker* implements endpoints and TradingView calls them, so their charts can route orders. This is how the Tradovate link works. | No — it is for brokerages integrating with TradingView. |
| **Advanced Charts / Charting Library** | A licensed copy of their chart widget that you embed in your own app and **feed with your own data**. | Licence only, and it supplies no data. |
| **Embeddable widgets** | Display-only chart/quote widgets for websites. | Yes, but display only. |

Webhook specifics worth knowing (from their docs):

- POSTs come from `52.89.214.238`, `34.212.75.30`, `54.218.53.128`, `52.32.178.7`.
- Only ports 80 and 443. IPv6 unsupported.
- Your endpoint must respond within 3 seconds or the request is cancelled.
- Never put credentials in the webhook body.

## What gets marketed as a "TradingView API key"

1. **Third-party data resellers** — e.g. `tradingviewapi.com`, sold through RapidAPI. Not
   TradingView, not their data licence, and not their support if it breaks.
2. **Unofficial scraper libraries** — `Mathieu2301/TradingView-API`, `tvdatafeed` and similar
   log in as you and read TradingView's internal websocket. This violates their terms and
   risks your TradingView account. It is also fragile: it breaks whenever they change the
   protocol.
3. **Webhook bridges** — PickMyTrade, TradersPost, and the rest. These are the "AI trading"
   integrations you have seen. They receive your TradingView alert and place the order at the
   broker for you. Legitimate software; the compliance question is not theirs, it is Apex's.

## Tradovate's API — the answer that matters for us

From Tradovate's own help centre, verbatim:

> "Prop firm and evaluation accounts are not eligible for API access. A live, funded
> Tradovate brokerage account is required."

Also: $1,000 minimum balance, $25/month for the add-on, and real-time market data is **not**
included. So there is no sanctioned API route to an Apex account — not even read-only for the
journal. Data has to move by CSV export.

## The compliance contradiction, stated plainly

The bridge vendors claim Apex allows this. PickMyTrade's site says Apex's rules "permit
semi-automated trading — a trader-supervised strategy where alerts route through a webhook
bridge." Apex's own Prohibited Activities page says:

> "No Automation or Algorithm Usage allowed: Rewards are intended to recognize human traders
> actively participating in the learning process, not to reward automated systems executing
> preprogrammed logic."

Those cannot both be true as written. Apex also publishes a page about a Tradovate API
request limit (reportedly 5,000/hour), which suggests some API traffic is expected on Apex
accounts — that page is behind Cloudflare and I could not read it.

The people selling bridges are paid when you decide it is allowed. The penalty if they are
wrong is forfeiture of the account and its balance. If you want to pursue it, get a written
answer from Apex support first — and note that automation was never your bottleneck.

## What we can do with no API at all

- **Backtesting**: Pine scripts in the Strategy Tester, over your full MES history.
- **Getting results out**: Strategy Tester → "List of Trades" → CSV → `replay.py`.
- **Getting your real fills out**: Tradovate web → Reports → CSV → `replay.py`.
- **Alerts as notifications to you**: a Pine `alert()` that fires "ORB long, stop 6.5 pts,
  target 13 pts" to your phone, which *you* then act on by hand. No bridge, no order routing,
  no automation — and it removes the need to stare at the chart waiting for the break.
