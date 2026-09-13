"""Render the week's model numbers as a publishable page.

The content product, generated rather than written: one card per game with the
model number next to the market number, the market note where there is one, and
last week's scored record at the top. No game footage anywhere in it, which is
the entire point -- footage is fingerprinted and monetized by the league, so a
page built from original numbers is the only version of this that pays.

Also emits a 1080x1350 PNG of the same page for Instagram, so the post and the
page cannot say different things.

Run: python3 weekly_post.py [--out path] [--season S --week W] [--no-image]
"""
import argparse
import datetime
import html
import os
import shutil
import subprocess
import zoneinfo

import pandas as pd

import game_model
import market_flow

try:
    from PIL import Image
except ImportError:            # the page still generates without the image
    Image = None

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
.signup{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:16px;margin-top:22px}
.signup h2{font-size:17px;margin:0 0 6px;letter-spacing:-.01em}
.signup p{color:var(--dim);font-size:13.5px;margin:0 0 12px}
.signup form{display:flex;gap:8px}
.signup input{flex:1;min-width:0;background:#0f1115;color:var(--text);
border:1px solid var(--line);border-radius:10px;padding:11px 12px;font:inherit}
.signup input:focus{outline:none;border-color:var(--model)}
.signup button{background:var(--model);color:#fff;border:0;border-radius:10px;
padding:11px 16px;font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
.signup .fine{font-size:11.5px;margin:10px 0 0}
.signup .msg{font-size:13px;margin:10px 0 0;color:var(--model)}
.inbio{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:16px;margin-top:22px;text-align:center}
.inbio h2{font-size:17px;margin:0 0 4px}
.inbio p{color:var(--dim);font-size:13.5px;margin:0}
@media(max-width:420px){.nums{grid-template-columns:1fr}
.signup form{flex-direction:column}}
"""

# The offer, worded so it can be kept every week for years. Not "picks": the
# model loses to the closing line, so promising winners is promising the one
# thing the measurements say cannot be delivered.
OFFER = ("My model's number for every game next to Vegas's number, plus how "
         "last week's predictions actually did — emailed before Sunday. "
         "Free, and no picks are sold here.")

SIGNUP = f"""<div class="signup"><h2>Get it in your inbox</h2>
<p>{OFFER}</p>
<form method="post" action="/subscribe" id="su">
<input type="email" name="email" required autocomplete="email"
 placeholder="you@email.com" aria-label="Email address">
<input type="hidden" name="source" value="week-page">
<button type="submit">Send it to me</button></form>
<p class="msg" id="sm" hidden></p>
<p class="fine">One email a week during the season. Every one has an
unsubscribe link that works in one click. Your address is not sold or
shared.</p></div>
<script>
var f=document.getElementById('su'),m=document.getElementById('sm');
f.addEventListener('submit',function(e){{
  e.preventDefault();
  var b=f.querySelector('button'),email=f.email.value;
  b.disabled=true;
  fetch('/subscribe',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{email:email,source:'week-page'}})}})
  .then(function(r){{return r.json().then(function(j){{return [r.ok,j]}})}})
  .then(function(p){{
    m.hidden=false;b.disabled=false;
    m.textContent=p[0]?"You're on the list. Look for it before Sunday."
      :(p[1].error||'That did not go through.');
    if(p[0]){{f.reset()}}
  }}).catch(function(){{b.disabled=false;f.submit()}});
}});
</script>"""

# Instagram is a fixed 1080x1350 frame, so the post cannot be a crop of the
# scrolling page -- that truncates mid-card and drops most of the slate. Every
# game has to fit at once, which means one dense row each.
POST_CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--text:#e8eaed;
--dim:#9aa0ac;--model:#a371f7;--market:#58a6ff}
*{box-sizing:border-box;margin:0}
body{width:1080px;height:1350px;background:var(--bg);color:var(--text);
font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
padding:44px 48px;display:flex;flex-direction:column;overflow:hidden}
h1{font-size:48px;letter-spacing:-.03em;line-height:1.05;flex-shrink:0}
.sub{color:var(--dim);font-size:20px;margin-top:8px;flex-shrink:0}
.legend{display:flex;gap:20px;font-size:18px;margin:18px 0 10px;flex-shrink:0}
.legend b{font-weight:600}
.legend .m{color:var(--market)}
.legend .p{color:var(--model)}
.rows{flex:1 1 0;display:flex;flex-direction:column;gap:6px;min-height:0}
.r{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:0 18px;display:grid;grid-template-columns:1fr 128px 128px 90px;
align-items:center;gap:12px;flex:1 1 0;min-height:0;overflow:hidden}
.t{font-size:23px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.t span{color:var(--dim);font-weight:400;font-size:19px;margin:0 7px}
.n{font-size:24px;font-variant-numeric:tabular-nums;font-weight:600;
text-align:right}
.n.m{color:var(--market)}
.n.p{color:var(--model)}
.d{text-align:right;font-size:19px;font-variant-numeric:tabular-nums;
color:var(--dim)}
.d.big{color:var(--model);font-weight:600}
footer{margin-top:16px;border-top:1px solid var(--line);padding-top:16px;
display:flex;justify-content:space-between;align-items:flex-end;gap:24px;
flex-shrink:0}
footer .l{font-size:20px;color:var(--dim);max-width:640px}
footer .l b{color:var(--text)}
footer .cta{text-align:right;font-size:21px;font-weight:600;white-space:nowrap}
footer .cta span{display:block;font-size:16px;font-weight:400;
color:var(--dim);margin-top:4px}
"""


def post_render(season, week, rows, rec, now):
    """The Instagram frame: the whole slate at a glance, no form, no scroll.

    Carries the same two numbers per game as the page and the same honest
    footer, so the post cannot promise more than the page delivers.
    """
    o = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
         f"<style>{POST_CSS}</style></head><body>",
         f"<h1>Week {week}: my model vs the market</h1>",
         f'<div class="sub">All {len(rows)} games \u00b7 posted '
         f"{now:%A %B %-d} \u00b7 before kickoff</div>",
         '<div class="legend"><b class="m">Vegas</b>'
         '<b class="p">My model</b>'
         '<b style="color:#9aa0ac">Gap</b></div>',
         '<div class="rows">']

    for r in rows:
        mteam, mby = side(r["spread_line"], r["home"], r["away"])
        team, by = side(r["pred_margin"], r["home"], r["away"])
        gap = abs(r["pred_margin"] - r["spread_line"])
        o.append(
            f'<div class="r"><div class="t">{html.escape(TEAMS[r["away"]])}'
            f'<span>at</span>{html.escape(TEAMS[r["home"]])}</div>'
            f'<div class="n m">{mteam} \u2212{mby:.1f}</div>'
            f'<div class="n p">{team} \u2212{by:.1f}</div>'
            f'<div class="d{" big" if gap >= 2.5 else ""}">'
            f'{gap:.1f}</div></div>')
    o.append("</div>")

    if rec:
        left = (f"<b>Last week, scored:</b> {rec['su']:.0%} straight up on "
                f"{rec['n']} games. My average miss {rec['mae']:.1f} points, "
                f"Vegas {rec['mkt_mae']:.1f}. I post that either way.")
    else:
        left = ("<b>Every prediction gets scored here</b> the week after, "
                "including the weeks it goes badly.")
    o.append(f'<footer><div class="l">{left}</div>'
             '<div class="cta">Free weekly email'
             "<span>link in bio \u00b7 no picks sold</span></div>"
             "</footer></body></html>")
    return "\n".join(o)


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

    o.append(SIGNUP)

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


POST_W, POST_H = 1080, 1350   # Instagram's 4:5 portrait frame


def to_png(src, dest):
    """Screenshot the post layout to Instagram's 4:5 frame.

    Headless Chrome renders it rather than an image library, so the post is
    built from the same HTML and CSS as the page and the two cannot drift apart.

    The window is asked for taller than the frame on purpose: Chrome reserves
    part of --window-size for browser chrome, leaving a viewport ~87px short,
    and anything below that viewport is never painted -- which silently cut the
    footer off the first version of this image. Rendering tall and cropping the
    top is exact regardless of how much Chrome reserves.
    """
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser")
                   if shutil.which(c)), None)
    if not chrome:
        print("no chrome found, skipping the image")
        return False
    raw = dest + ".raw.png"
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--hide-scrollbars", "--force-device-scale-factor=1",
           f"--window-size={POST_W},{POST_H + 200}", f"--screenshot={raw}",
           "--default-background-color=0f1115", f"file://{src}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(raw):
        print(f"chrome could not render the image: {r.stderr.strip()[:200]}")
        return False
    if Image is None:
        os.replace(raw, dest)
        print(f"pillow missing: {dest} is uncropped, check it before posting")
        return False
    with Image.open(raw) as im:
        im.crop((0, 0, POST_W, POST_H)).save(dest)
    os.remove(raw)
    return True


def build(season=None, week=None, out=OUT, image=True):
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

    rec = last_week(df, season, week)
    now = datetime.datetime.now(PACIFIC)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(render(season, week, rows, rec, now))
    print(f"wrote {out}: {len(rows)} games")
    if image:
        shot = os.path.splitext(out)[0] + "_post.html"
        with open(shot, "w") as fh:
            fh.write(post_render(season, week, rows, rec, now))
        png = os.path.splitext(out)[0] + ".png"
        if to_png(shot, png):
            print(f"wrote {png}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--no-image", action="store_true",
                    help="skip the Instagram screenshot")
    a = ap.parse_args()
    build(a.season, a.week, a.out, image=not a.no_image)
