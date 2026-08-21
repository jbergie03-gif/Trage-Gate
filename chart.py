"""Candlestick chart of one paper session: the day's bars, the opening range, and every
trade the rules took, drawn on Jonathan's clock (Pacific).

The engine works on 1-minute bars; the chart aggregates them into 5-minute candles so the
entries and exits are readable. The markers stay on their exact minute either way.

Written by `paper_engine.py` next to the session report. Pure picture — it reads what the
engine already recorded and never touches the journal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

LONG = "#1a7f37"
SHORT = "#c62828"
STOP = "#b0413e"
LEVEL = "#4a5568"

# The picture is about the trading day, not the overnight drift: bars outside this Pacific
# window are dropped unless that would leave nothing to draw.
WINDOW = (time(6, 15), time(13, 5))

CANDLE_MINUTES = 3


@dataclass
class _Candle:
    """An aggregated candle. Same shape as the engine's `Bar`, built from several of them."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float


def _pt(ts: datetime) -> datetime:
    return ts.astimezone(PT)


def aggregate(bars: list, minutes: int) -> list:
    """1-minute bars into `minutes`-minute candles, on clock boundaries (06:30, 06:35, ...)."""
    if minutes <= 1:
        return list(bars)
    out: list = []
    bucket_start = None
    for b in bars:
        t = _pt(b.ts)
        start = t.replace(minute=t.minute - t.minute % minutes, second=0, microsecond=0)
        if bucket_start != start:
            bucket_start = start
            out.append(_Candle(start, b.open, b.high, b.low, b.close))
        else:
            c = out[-1]
            c.high = max(c.high, b.high)
            c.low = min(c.low, b.low)
            c.close = b.close
    return out


def write_chart(session, path: Path, exit_rule: str = "",
                minutes: int = CANDLE_MINUTES) -> Path | None:
    """Draw the session and save a PNG. Returns None if matplotlib is not installed."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return None

    bars = [b for b in session.bars_seen if WINDOW[0] <= _pt(b.ts).time() <= WINDOW[1]] \
        or list(session.bars_seen)
    if not bars:
        return None

    bars = aggregate(bars, minutes)
    times = [_pt(b.ts) for b in bars]
    width = (minutes / (24 * 60)) * 0.7      # candle body, in day units

    fig, ax = plt.subplots(figsize=(13, 6.5))
    for b, t in zip(bars, times):
        up = b.close >= b.open
        colour = LONG if up else SHORT
        x = mdates.date2num(t)
        ax.vlines(x, b.low, b.high, color=colour, linewidth=0.7, zorder=2)
        lo, hi = sorted((b.open, b.close))
        ax.add_patch(plt.Rectangle((x - width / 2, lo), width, max(hi - lo, 1e-9),
                                   facecolor=colour, edgecolor=colour, zorder=3))

    if session.or_high is not None and session.or_low is not None:
        ax.axhline(session.or_high, color=LEVEL, linewidth=0.9, linestyle=":", zorder=1)
        ax.axhline(session.or_low, color=LEVEL, linewidth=0.9, linestyle=":", zorder=1)
        ax.annotate(f"opening range {session.or_high:.2f} / {session.or_low:.2f}"
                    f"  ({session.or_high - session.or_low:.2f} pts)",
                    xy=(mdates.date2num(times[-1]), session.or_high),
                    xytext=(-3, 5), textcoords="offset points", ha="right",
                    fontsize=8, color=LEVEL, zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                              edgecolor="none", alpha=0.75))

    day = times[0].date()
    for t in session.trades:
        opened = _mark_time(t.get("opened_ts"), t["opened"], day)
        closed = _mark_time(t.get("closed_ts"), t["closed"], day)
        if opened is None or closed is None:
            continue
        x0, x1 = mdates.date2num(opened), mdates.date2num(closed)
        won = t["pnl"] > 0
        colour = LONG if won else SHORT
        marker = "^" if t["side"] == "long" else "v"

        ax.plot([x0, x1], [t["entry"], t["exit"]], color=colour, linewidth=1.4,
                alpha=0.85, zorder=4)
        ax.plot([x0], [t["entry"]], marker=marker, color=colour, markersize=10,
                markeredgecolor="white", markeredgewidth=0.8, zorder=5)
        ax.plot([x1], [t["exit"]], marker="X", color=colour, markersize=10,
                markeredgecolor="white", markeredgewidth=0.8, zorder=5)
        ax.hlines(t["stop"], x0, x1, color=STOP, linewidth=0.9, linestyle="--",
                  alpha=0.8, zorder=4)
        ax.annotate(f"{t.get('setup', 'ORB')} {t['side']} {t['contracts']} @ {t['entry']:.2f}"
                    f"  ${t['pnl']:+,.2f} ({t['r']:+.2f}R)",
                    xy=(x0, t["entry"]), xytext=(8, 14 if t["side"] == "long" else -22),
                    textcoords="offset points", fontsize=8.5, color=colour,
                    fontweight="bold", ha="left", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                              edgecolor="none", alpha=0.75))

    net = sum(t["pnl"] for t in session.trades)
    title = f"Paper session {session.date} — net ${net:+,.2f}"
    if exit_rule:
        title += f" · exit {exit_rule}"
    ax.set_title(f"{title}  ({minutes}-minute candles, simulated fills on delayed "
                 f"1-minute data)", fontsize=11)
    ax.set_ylabel("MES price")
    ax.set_xlabel("Pacific time")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=PT))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=range(0, 60, 30), tz=PT))
    ax.grid(alpha=0.15, zorder=0)
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _mark_time(iso: str | None, hhmm: str, day) -> datetime | None:
    """Trade times are recorded as PT "HH:MM" for the report; an ISO stamp is used when present."""
    if iso:
        try:
            return _pt(datetime.fromisoformat(iso))
        except ValueError:
            pass
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PT)
