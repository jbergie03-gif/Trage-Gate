#!/usr/bin/env python3
"""Years of 1-minute S&P 500 history, free and without an account.

The free Yahoo feed the daily engine uses only serves ~30 days of 1-minute bars, which is too
short to judge a rule change. Dukascopy publishes its raw tick archive over plain HTTP with no
key, no signup and no rate plan — including `USA500IDXUSD`, its S&P 500 cash-index CFD, back to
roughly 2017. This downloads the hours covering Jonathan's session, aggregates the ticks to
1-minute OHLC bars in Pacific time, and writes the same CSV shape the lab studies already read:

    Datetime,Open,High,Low,Close,Volume

    python lab/deep_history.py --years 2                     # -> data/SP500_1min_deep.csv
    python lab/deep_history.py --start 2024-01-01 --end 2024-07-01

Read the caveats before trusting a backtest built on this:

* It is the cash index CFD, not ES or MES. Futures trade at a basis to the index (tens of points,
  drifting with rates and dividends) so absolute prices differ, but the intraday path — which is
  all an opening-range rule cares about — tracks closely.
* Bars are built from bid ticks. Volume is Dukascopy's tick volume, not exchange volume.
* Minutes with no tick are absent rather than filled forward.

Files are cached under `~/.cache/dukascopy` so a re-run costs nothing.
"""
import argparse
import datetime as dt
import lzma
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "SP500_1min_deep.csv"
CACHE = Path.home() / ".cache" / "dukascopy"
PT = ZoneInfo("America/Los_Angeles")
UTC = dt.timezone.utc

INSTRUMENT = "USA500IDXUSD"
URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"
PRICE_SCALE = 1000.0     # the feed stores index prices as 1/1000ths
TICK = struct.Struct(">IIIff")   # ms into the hour, ask, bid, ask volume, bid volume

# The session Jonathan trades, 06:25–13:00 PT, plus an hour of slack either side of the DST shift.
PT_FIRST_HOUR, PT_LAST_HOUR = 6, 13


def _hours_for(day: dt.date) -> list[int]:
    """UTC hours covering 06:00–13:59 PT on `day`."""
    hours = set()
    for hour in range(PT_FIRST_HOUR, PT_LAST_HOUR + 1):
        local = dt.datetime.combine(day, dt.time(hour), tzinfo=PT)
        utc = local.astimezone(UTC)
        if utc.date() == day:
            hours.add(utc.hour)
    return sorted(hours)


def _download(day: dt.date, hour: int, tries: int = 6) -> bytes | None:
    """One hour of ticks, cached. `None` when the archive genuinely has no such hour.

    Only a 404 is final — a holiday, or a date before the archive starts — and it gets a marker
    file so a re-run does not ask again. Everything else is retried with a backoff, *including an
    empty 200*: that is how the archive answers a burst it does not like, and caching it as "no
    ticks this hour" silently punches holes in the sample that a re-run can never fill.
    """
    stem = CACHE / INSTRUMENT / f"{day:%Y-%m-%d}-{hour:02d}"
    data_path, missing_path = stem.with_suffix(".bi5"), stem.with_suffix(".404")
    if data_path.exists():
        return data_path.read_bytes()
    if missing_path.exists():
        return None
    data_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = stem.with_suffix(".part")
    url = URL.format(sym=INSTRUMENT, y=day.year, m=day.month - 1, d=day.day, h=hour)
    for attempt in range(tries):
        proc = subprocess.run(["curl", "-sS", "--max-time", "45", "-A", "Mozilla/5.0",
                               "-o", str(tmp), "-w", "%{http_code}", url],
                              capture_output=True, text=True)
        code = proc.stdout.strip()[-3:] if proc.stdout else ""
        body = tmp.read_bytes() if tmp.exists() else b""
        tmp.unlink(missing_ok=True)
        if proc.returncode == 0 and code == "200" and body:
            data_path.write_bytes(body)
            return body
        if code == "404":
            missing_path.touch()
            return None
        time.sleep(2 + 4 * attempt)
    return None


def _ticks(day: dt.date, hour: int) -> list[tuple[dt.datetime, float]]:
    """Decode an hour into (timestamp, bid price) pairs."""
    raw = _download(day, hour)
    if not raw:
        return []
    try:
        data = lzma.LZMADecompressor().decompress(raw)
    except lzma.LZMAError:
        return []
    start = dt.datetime.combine(day, dt.time(hour), tzinfo=UTC)
    out = []
    for i in range(len(data) // TICK.size):
        ms, _ask, bid, _av, _bv = TICK.unpack_from(data, i * TICK.size)
        out.append((start + dt.timedelta(milliseconds=ms), bid / PRICE_SCALE))
    return out


def bars(start: dt.date, end: dt.date, workers: int = 8) -> pd.DataFrame:
    """1-minute OHLC bars in Pacific time for every weekday in [start, end)."""
    days = [start + dt.timedelta(days=i) for i in range((end - start).days)]
    days = [d for d in days if d.weekday() < 5]
    jobs = [(d, h) for d in days for h in _hours_for(d)]
    cached = sum(1 for d, h in jobs
                 if (CACHE / INSTRUMENT / f"{d:%Y-%m-%d}-{h:02d}.bi5").exists())
    print(f"{len(days)} weekdays, {len(jobs)} hourly files ({cached} already cached)", flush=True)

    rows: list[tuple[dt.datetime, float]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(lambda job: _ticks(*job), jobs):
            rows.extend(got)
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(jobs)} hours, {len(rows):,} ticks", flush=True)
    if not rows:
        return pd.DataFrame()

    ser = pd.Series({ts: px for ts, px in rows}).sort_index()
    ser.index = pd.DatetimeIndex(ser.index).tz_convert(PT)
    ohlc = ser.resample("1min").ohlc().dropna()
    ohlc.columns = ["Open", "High", "Low", "Close"]
    counts = ser.resample("1min").count()
    ohlc["Volume"] = counts.reindex(ohlc.index).astype(int)     # tick count, not exchange volume
    ohlc.index.name = "Datetime"
    return ohlc[(ohlc.index.time >= dt.time(6, 25)) & (ohlc.index.time <= dt.time(12, 55))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=float, default=2.0, help="how far back to go from today")
    ap.add_argument("--start", help="YYYY-MM-DD, overrides --years")
    ap.add_argument("--end", help="YYYY-MM-DD, exclusive")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    start = (dt.date.fromisoformat(args.start) if args.start
             else end - dt.timedelta(days=round(args.years * 365)))

    df = bars(start, end, args.workers)
    if df.empty:
        raise SystemExit("no bars — the archive returned nothing for that range")
    df.to_csv(args.out)
    per_day = df.groupby(df.index.date).size()
    print(f"{len(df):,} bars over {len(per_day)} sessions, "
          f"{df.index[0].date()} → {df.index[-1].date()} -> {args.out}")
    thin = per_day[per_day < 300]        # a whole 06:25–12:55 session is ~390 bars
    print(f"{len(thin)} sessions still have gaps (under 300 bars) — re-run to fill them, "
          f"the cache makes it cheap" if len(thin) else "every session looks complete")


if __name__ == "__main__":
    main()
