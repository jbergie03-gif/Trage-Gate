"""Render the week's model numbers as a publishable page.

The content product, generated rather than written: one card per game with the
model number next to the market number, the market note where there is one, and
last week's scored record at the top. No game footage anywhere in it, which is
the entire point -- footage is fingerprinted and monetized by the league, so a
page built from original numbers is the only version of this that pays.

Run: python3 weekly_post.py [--out path] [--season S --week W]
"""
import argparse
import datetime
import html
import os
import zoneinfo

import pandas as pd

import game_model
import market_flow

GAMES = game_model.GAMES
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ET = zoneinfo.ZoneInfo("America/New_York")
OUT = os.path.expanduser("~/nflmodel/out/week.html")

TEAMS = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}


def kickoff(row):
    """Kickoff in Pacific. games.csv times are Eastern."""
    t = str(row.get("gametime") or "13:00")
    if ":" not in t:
        t = "13:00"
    hh, mm = (int(x) for x in t.split(":")[:2])
    d = datetime.date.fromisoformat(str(row["gameday"]))
    et = datetime.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)
    return et.astimezone(PACIFIC)


def side(margin, home, away):
    """Which team a home-margin number favors, and by how much."""
    return (home, margin) if margin > 0 else (away, -margin)


def read(edge):
    """The sentence under each game. Sub-point edges are called coin flips
    explicitly rather than dressed up, because that is what they are against a
    10-point per-game error."""
    a = abs(edge)
    if a < 1:
        return "Model and market agree. Coin flip."
    if a < 2.5:
        return "Slight lean, inside the model's error bar."
    if a < 5:
        return "Real disagreement with the market."
    return "Biggest disagreement on the board — usually the model missing news."


def last_week(df, season, week):
    """Score the most recent completed week, or None before the first one."""
    prev = df[(df["season"] == season) & (df["week"] < week)
              & df["result"].notna() & df["spread_line"].notna()]
    if prev.empty:
        return None
    p = game_model.fit_report(df, first_test=season)
    p = p[(p["season"] == season) & (p["week"] == int(prev["week"].max()))]
    if p.empty:
        return None
    ats = p[p["result"] != p["spread_line"]]
    ou = p[p["total"] != p["total_line"]]
    return dict(
        week=int(p["week"].iloc[0]),
        n=len(p),
        su=((p.pred_margin > 0) == (p.result > 0)).mean(),
        mae=(p.pred_margin - p.result).abs().mean(),
        mkt_mae=(p.spread_line - p.result).abs().mean(),
        ats=((ats.pred_margin - ats.spread_line)
             * (ats.result - ats.spread_line) > 0).mean() if len(ats) else None,
        ou=((ou.pred_total - ou.total_line)
            * (ou.total - ou.total_line) > 0).mean() if len(ou) else None,
    )


CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--text:#e8eaed;
--dim:#9aa0ac;--model:#a371f7;--market:#58a6ff;--warn:#d9a20b}
*{box-sizing:border-box}
body{margin:0;padding:20px 12px 80px;background:var(--bg);color:var(--text);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
header,main,footer{max-width:660px;margin:0 auto}
h1{font-size:26px;letter-spacing:-.02em;margin:0 0 6px}
.sub{color:var(--dim);font-size:13px;margin-bottom:22px}
.record{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;margin-bottom:22px}
.record h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;
color:var(--dim);margin:0 0 12px;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(72px,1fr));gap:12px}
.stat .v{font-size:20px;font-variant-numeric:tabular-nums;font-weight:600}
.stat .k{font-size:11px;color:var(--dim);margin-top:2px}
.game{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;margin-bottom:12px}
.when{display:flex;justify-content:space-between;color:var(--dim);
font-size:12px;margin-bottom:10px}
.matchup{font-size:19px;font-weight:600;letter-spacing:-.01em;margin-bottom:12px}
.matchup .at{color:var(--dim);font-weight:400;margin:0 4px}
.nums{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.num{border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.num .k{font-size:11px;letter-spacing:.06em;text-transform:uppercase;
color:var(--dim);margin-bottom:3px}
.num .v{font-size:17px;font-variant-numeric:tabular-nums;font-weight:600}
.num.market .v{color:var(--market)}
.num.model .v{color:var(--model)}
.bar{height:4px;border-radius:3px;background:#20242e;overflow:hidden;margin-bottom:10px}
.bar i{display:block;height:100%;background:var(--model)}
.read{font-size:14px;color:var(--dim)}
.note{margin-top:10px;padding:9px 11px;border-radius:10px;
background:#1e1a10;border:1px solid #3a2f12;font-size:13px;color:#e6d7a8}
footer{margin-top:28px;color:var(--dim);font-size:12.5px;border-top:1px solid var(--line);
padding-top:16px}
footer b{color:var(--text)}
@media(max-width:420px){.nums{grid-template-columns:1fr}}
"""


def render(season, week, rows, rec, now):
    o = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f"<title>NFL Week {week} — model vs the market</title>",
         f"<style>{CSS}</style></head><body>",
         f"<header><h1>Week {week} — model vs the market</h1>",
         f'<div class="sub">Posted {now:%A, %B %-d} at {now:%-I:%M %p} PT'
         " · every number below was public before kickoff</div></header><main>"]

    if rec:
        cells = [("straight up", f"{rec['su']:.0%}"),
                 ("model error", f"{rec['mae']:.1f}"),
                 ("market error", f"{rec['mkt_mae']:.1f}")]
        if rec["ats"] is not None:
            cells.append(("vs the line", f"{rec['ats']:.0%}"))
        if rec["ou"] is not None:
            cells.append(("over/under", f"{rec['ou']:.0%}"))
        o.append(f'<div class="record"><h2>Week {rec["week"]} results'
                 f' — {rec["n"]} games</h2><div class="stats">')
        for k, v in cells:
            o.append(f'<div class="stat"><div class="v">{v}</div>'
                     f'<div class="k">{k}</div></div>')
        o.append("</div></div>")

    for r in rows:
        team, by = side(r["pred_margin"], r["home"], r["away"])
        mteam, mby = side(r["spread_line"], r["home"], r["away"])
        edge = r["pred_margin"] - r["spread_line"]
        fill = min(abs(edge) / 7 * 100, 100)
        tot = ("—" if pd.isna(r["total_line"]) else f"{r['total_line']:.1f}")
        o.append('<div class="game">'
                 f'<div class="when"><span>{r["kick"]:%a %-I:%M %p} PT</span>'
                 f'<span>total {tot} · model {r["pred_total"]:.1f}</span></div>'
                 f'<div class="matchup">{html.escape(TEAMS[r["away"]])}'
                 f'<span class="at">at</span>{html.escape(TEAMS[r["home"]])}</div>'
                 '<div class="nums">'
                 f'<div class="num market"><div class="k">Market</div>'
                 f'<div class="v">{mteam} −{mby:.1f}</div></div>'
                 f'<div class="num model"><div class="k">My model</div>'
                 f'<div class="v">{team} −{by:.1f}</div></div></div>'
                 f'<div class="bar"><i style="width:{fill:.0f}%"></i></div>'
                 f'<div class="read">{html.escape(read(edge))}</div>')
        if r["note"]:
            o.append(f'<div class="note">{html.escape(r["note"])}</div>')
        o.append("</div>")

    o.append("</main><footer><b>How to read this.</b> Both numbers are the "
             "expected home margin. Mine comes from a ridge model on "
             "opponent-adjusted efficiency, quarterback value, the injury "
             "report, rest and travel — fit only on games played before the "
             "one it is predicting.<br><br>"
             "<b>Out of sample it does not beat the closing line:</b> 10.23 "
             "points of average error against the market's 9.82 over 1,962 "
             "games, and 48.3% against the spread. That is published here for "
             "the same reason the numbers are: a record you can check is the "
             "product. <b>None of this is a bet or advice.</b>"
             "</footer></body></html>")
    return "\n".join(o)


def build(season=None, week=None, out=OUT):
    df = game_model.build(*game_model.load())
    if season is None or week is None:
        season, week = game_model.next_slate(df)
        if season is None:
            print("no upcoming games with a posted line")
            return None
    slate = game_model.predict_slate(df, season, week)
    times = pd.read_csv(GAMES, usecols=["game_id", "gametime"])
    slate = slate.merge(times, on="game_id", how="left")
    notes = market_flow.slate_notes(season, week)

    rows = [dict(home=r.home_team, away=r.away_team, kick=kickoff(r._asdict()),
                 spread_line=r.spread_line, total_line=r.total_line,
                 pred_margin=r.pred_margin, pred_total=r.pred_total,
                 note=notes.get((r.away_team, r.home_team)))
            for r in slate.itertuples()]
    rows.sort(key=lambda r: r["kick"])

    page = render(season, week, rows, last_week(df, season, week),
                  datetime.datetime.now(PACIFIC))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(page)
    print(f"wrote {out}: {len(rows)} games")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    a = ap.parse_args()
    build(a.season, a.week, a.out)
