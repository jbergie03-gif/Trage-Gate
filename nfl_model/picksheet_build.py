"""Build the week's ATS pick sheet from the model and the current DK lines.

The sheet used to be hand-assembled, and week 1 shows why that is a bad idea:
the Thursday, Sunday-night and Monday-night games were simply left off it, so
three games of the week could not be picked at all. This builds the whole week
off the schedule instead, Thursday through Monday, so nothing can be forgotten.

Games that have already kicked off are marked locked: the card is a record of
picks made before kickoff, and a sheet that lets a game be picked while it is
being played destroys that.

Devin's side is the model's, and the two largest disagreements with the market
get the double weight -- the same rule every week rather than a judgment call.

Run: python3 picksheet_build.py [--out picksheet/index.html]
                               [--season S --week W] [--stars N]
"""
import argparse
import datetime
import json
import os
import zoneinfo

import pandas as pd

import game_model
import input_check
import weekly_post

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "picksheet", "template.html")
OUT = os.path.join(ROOT, "picksheet", "index.html")
ODDS = os.path.join(ROOT, "data", "odds_snapshots.csv")
BOOK = "draftkings"
STARS = 2


def dk_lines():
    """The most recent DraftKings snapshot, keyed by (away, home, date).

    Keyed on the date as well as the teams because divisional opponents meet
    twice a season, and the same pair of abbreviations would otherwise collide.
    """
    if not os.path.exists(ODDS):
        return {}, None
    d = pd.read_csv(ODDS)
    d = d[d["book"] == BOOK]
    if d.empty:
        return {}, None
    taken = d["taken_at_pt"].max()
    d = d[d["taken_at_pt"] == taken]
    out = {}
    for r in d.itertuples():
        start = pd.to_datetime(r.commence_time, utc=True)
        day = start.tz_convert(PACIFIC).date()
        out[(r.away, r.home, day)] = (r.spread_line, r.total_line)
    stamp = pd.to_datetime(taken).strftime("%Y-%m-%d %H:%M PT")
    return out, stamp


def note(edge):
    """The line under each game once Devin's card is revealed.

    A sub-point edge is called a coin flip in as many words. The model's mean
    error is about 10 points a game, so anything smaller than a point is not an
    opinion and should not be dressed up as one.
    """
    a = abs(edge)
    if a < 1:
        return "coin flip, no opinion"
    if a < 2.5:
        return f"model edge {a:.1f}, inside its error bar"
    return f"model edge {a:.1f}"


def week_lines(df, season, week, lines):
    """Every game of the week, with the DK number filled in where we have one.

    predict_slate() drops a game whose schedule row has no spread yet, which is
    exactly how a Thursday or Monday game disappears from the sheet. So the DK
    number is written into the frame first: a game the book has priced gets a
    prediction even when the schedule file has not caught up.
    """
    if "gametime" not in df.columns:
        times = pd.read_csv(game_model.GAMES, usecols=["game_id", "gametime"])
        df = df.merge(times, on="game_id", how="left")
    wk = df[(df["season"] == season) & (df["week"] == week)]
    kicks = {}
    for i, r in wk.iterrows():
        kicks[i] = weekly_post.kickoff(r.to_dict())
        dk = lines.get((r["away_team"], r["home_team"], kicks[i].date()))
        if dk and not any(pd.isna(x) for x in dk):
            df.loc[i, ["spread_line", "total_line"]] = dk
    df["kick_pt"] = pd.Series(kicks, dtype=object)
    return df


def rows(df, season, week, stars=STARS, now=None):
    lines, stamp = dk_lines()
    df = week_lines(df, season, week, lines)
    slate = game_model.predict_slate(df, season, week)
    pred = {r.game_id: r.pred_margin for r in slate.itertuples()}
    now = now or datetime.datetime.now(PACIFIC)

    out = []
    for r in df[(df["season"] == season) & (df["week"] == week)].itertuples():
        kick = r.kick_pt
        spread, total = r.spread_line, r.total_line
        started = kick <= now
        g = dict(away=r.away_team, home=r.home_team,
                 day=kick.strftime("%A"),
                 kick=kick.strftime("%a %-I:%M %p PT"),
                 kickAt=kick.isoformat(),
                 _kick=kick)
        if pd.isna(spread) or pd.isna(total) or r.game_id not in pred:
            # Shown anyway, unpickable. Dropping a game for having no line is
            # how a game goes missing from the sheet, which is the bug this
            # file exists to prevent -- regenerate once the book posts it.
            out.append(dict(g, spread=None, total=None, devin="",
                            devinNote="no line posted", _locked=True,
                            _edge=-1))
            continue
        edge = pred[r.game_id] - spread
        home = edge > 0
        team = r.home_team if home else r.away_team
        num = -spread if home else spread
        out.append(dict(
            g, spread=round(float(spread), 1), total=round(float(total), 1),
            devin=f"{team} {'+' if num > 0 else ''}{num:.1f}",
            devinNote=note(edge),
            _locked=started,
            _edge=abs(edge),
        ))
    out.sort(key=lambda g: g["_kick"])
    for g in sorted((g for g in out if not g["_locked"]),
                    key=lambda g: -g["_edge"])[:stars]:
        g["devinDouble"] = True
    for g in out:
        del g["_edge"], g["_kick"]
    return out, stamp


def build(season=None, week=None, out=OUT, stars=STARS, fact_check=True):
    df = game_model.build(*game_model.load())
    auto = season is None or week is None
    if auto:
        season, week = game_model.next_slate(df)
        if season is None:
            print("no upcoming games with a posted line")
            return None
    games, stamp = rows(df, season, week, stars)
    if not games:
        print(f"no games with a line for {season} week {week}")
        return None
    if not any(not g["_locked"] for g in games) and auto:
        # Every game of that week is played; the sheet people want is next
        # week's. next_slate() still names the old week until the results land.
        print(f"{season} week {week} is over, building week {week + 1}")
        nxt, stamp = rows(df, season, week + 1, stars)
        if nxt:
            games, week = nxt, week + 1

    live = [g for g in games if not g["_locked"]]
    pending = [g for g in games if g["spread"] is None]
    for g in pending:
        print(f"no line yet for {g['away']}@{g['home']} ({g['kick']})")
    title = f"{season} Week {week}"
    # With one game left there is no point offering two doubles.
    doubles = min(stars, len(live))
    scoring = (f"{len(live)} game(s) still open of {len(games)} this week, "
               f"{len(live) + doubles} points available.")
    # The sheet recomputes locked from kickAt against the reader's clock, so
    # the build-time flag is a build detail and does not ship.
    for g in games:
        del g["_locked"]
    with open(TEMPLATE) as fh:
        page = fh.read()
    slate = f"{season}-w{week:02d}"
    for key, val in (("__TITLE__", title),
                     ("__SLATE__", slate),
                     ("__TAKEN__", stamp or "the schedule, no DK snapshot"),
                     ("__SCORING__", scoring),
                     ("__MAX_STARS__", str(doubles)),
                     ("__GAMES__", json.dumps(games, indent=2))):
        page = page.replace(key, val)
    with open(out, "w") as fh:
        fh.write(page)
    # Kickoff times for the card API to enforce, since the page's own lock is
    # JavaScript over editable storage and /card can be POSTed directly.
    locks = os.path.join(os.path.dirname(os.path.abspath(out)),
                         "kickoffs.json")
    with open(locks, "w") as fh:
        json.dump({slate: {f"{g['away']}@{g['home']}": g["kickAt"]
                           for g in games}}, fh, indent=2)
    kicked = len(games) - len(live) - len(pending)
    print(f"wrote {out} and {locks}: {len(games)} games, "
          f"{kicked} already kicked off, {len(pending)} waiting on a line")

    # The sheet is only as good as what the model was told. Week 2 was built
    # on a schedule file that had Tua Tagovailoa starting for Atlanta while he
    # had not practiced all week, and nothing in the build said so. Now the
    # check runs every time and prints, so a stale input has to be read past
    # rather than discovered afterwards.
    if fact_check:
        report = input_check.check(season, week, game_model.DATA)
        path = os.path.join(os.path.dirname(os.path.abspath(out)),
                            "input_check.md")
        with open(path, "w") as fh:
            fh.write("\n".join(report) + "\n")
        print("\n" + "\n".join(report))
        print(f"wrote {path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--stars", type=int, default=STARS)
    ap.add_argument("--no-check", action="store_true",
                    help="skip the input fact-check")
    a = ap.parse_args()
    build(a.season, a.week, a.out, a.stars, fact_check=not a.no_check)
