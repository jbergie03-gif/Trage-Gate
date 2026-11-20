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

A starter the schedule has wrong is fixed with --swap TEAM="QB Name" (the
same form input_check.py takes), and --fact TEAM="..." puts the sourced reason
under that team's game, so the sheet says why the model's quarterback differs
from the schedule.

Run: python3 picksheet_build.py [--out picksheet/index.html]
                               [--season S --week W] [--stars N]
                               [--swap TEAM="QB Name"] [--fact TEAM="text"]
"""
import argparse
import datetime
import json
import os
import zoneinfo

import pandas as pd

import game_model
import input_check
import site_chrome
import smash_feature
import total_model
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


def apply_swaps(g, season, week, swaps):
    """Put the named quarterback in the schedule row before the model reads it.

    The model takes its starter from games.csv (`home_qb_id`/`away_qb_id`), so
    editing that row is what makes the rating, the inexperience flag and the
    pick all follow the real starter.
    """
    if not swaps:
        return g
    players = pd.read_csv(os.path.join(game_model.DATA, "players.csv"),
                          low_memory=False)
    g = g.copy()
    wk = (g["season"] == season) & (g["week"] == week)
    for team, who in swaps:
        hit = players[(players["position"] == "QB")
                      & (players["display_name"].str.lower() == who.lower())]
        if hit.empty:
            raise SystemExit(f"--swap: no quarterback named {who}")
        qb_id = hit.iloc[0]["gsis_id"]
        found = False
        for side in ("home", "away"):
            m = wk & (g[f"{side}_team"] == team)
            if m.any():
                found = True
                print(f"swap {team}: {g.loc[m, f'{side}_qb_name'].iloc[0]}"
                      f" -> {who}")
                g.loc[m, f"{side}_qb_id"] = qb_id
                g.loc[m, f"{side}_qb_name"] = who
        if not found:
            raise SystemExit(f"--swap: {team} has no game in week {week}")
    return g


def rows(df, season, week, stars=STARS, now=None, facts=None):
    lines, stamp = dk_lines()
    df = week_lines(df, season, week, lines)
    slate = smash_feature.apply(game_model.predict_slate(df, season, week))
    smash_feature.log(slate, season, week)
    pred = {r.game_id: r.pred_margin for r in slate.itertuples()}
    totals = {r.game_id: (r.pred_total, r.blend_total)
              for r in total_model.predict_slate(df, season, week).itertuples()}
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
        if started:
            # Kicked off before this build: the card is a record of picks made
            # before kickoff, so the model makes none here after the fact.
            out.append(dict(g, spread=round(float(spread), 1),
                            total=round(float(total), 1), devin="",
                            devinNote="kicked off before the line snapshot"
                            " \u2014 no model pick",
                            _locked=True, _edge=-1))
            continue
        edge = pred[r.game_id] - spread
        home = edge > 0
        team = r.home_team if home else r.away_team
        num = -spread if home else spread
        model_total, blend_total = totals.get(r.game_id, (None, None))
        out.append(dict(
            g, spread=round(float(spread), 1), total=round(float(total), 1),
            devin=f"{team} {'+' if num > 0 else ''}{num:.1f}",
            devinNote="; ".join([note(edge)] + [
                facts[t] for t in (r.away_team, r.home_team)
                if facts and t in facts]),
            modelTotal=(None if model_total is None
                        else round(float(model_total), 1)),
            blendTotal=(None if blend_total is None
                        else round(float(blend_total), 1)),
            totalNote=("" if model_total is None
                       else total_model.note(model_total - total)),
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


def build(season=None, week=None, out=OUT, stars=STARS, fact_check=True,
          swaps=None, facts=None):
    g, tg, inj = game_model.load()
    df = game_model.build(g, tg, inj)
    auto = season is None or week is None
    if auto:
        season, week = game_model.next_slate(df)
        if season is None:
            print("no upcoming games with a posted line")
            return None
    games, stamp = rows(df, season, week, stars, facts=facts)
    if not games:
        print(f"no games with a line for {season} week {week}")
        return None
    if not any(not g["_locked"] for g in games) and auto:
        # Every game of that week is played; the sheet people want is next
        # week's. next_slate() still names the old week until the results land.
        print(f"{season} week {week} is over, building week {week + 1}")
        nxt, stamp = rows(df, season, week + 1, stars, facts=facts)
        if nxt:
            games, week = nxt, week + 1
    if swaps:
        # Swaps name the week being published, so apply them once it is known.
        df = game_model.build(apply_swaps(g, season, week, swaps), tg, inj)
        games, stamp = rows(df, season, week, stars, facts=facts)

    live = [g for g in games if not g["_locked"]]
    pending = [g for g in games if g["spread"] is None]
    for g in pending:
        print(f"no line yet for {g['away']}@{g['home']} ({g['kick']})")
    title = f"{season} Week {week}"
    # With one game left there is no point offering two doubles.
    doubles = min(stars, len(live))
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
                     ("__MAX_STARS__", str(doubles)),
                     ("__GAMES__", json.dumps(games, indent=2)),
                     ("__CHROME_CSS__", site_chrome.CSS),
                     ("__NAV__", site_chrome.nav("/"))):
        page = page.replace(key, val)
    with open(out, "w") as fh:
        fh.write(page)
    # Kickoff times for the card API to enforce, since the page's own lock is
    # JavaScript over editable storage and /card can be POSTed directly.
    # Other slates stay in the file: the late sheets under /sheets rely on
    # their kickoffs being there so /card keeps refusing them.
    locks = os.path.join(os.path.dirname(os.path.abspath(out)),
                         "kickoffs.json")
    known = {}
    if os.path.exists(locks):
        with open(locks) as fh:
            known = json.load(fh)
    known[slate] = {f"{g['away']}@{g['home']}": g["kickAt"] for g in games}
    with open(locks, "w") as fh:
        json.dump(dict(sorted(known.items())), fh, indent=2)
    kicked = len(games) - len(live) - len(pending)
    print(f"wrote {out} and {locks}: {len(games)} games, "
          f"{kicked} already kicked off, {len(pending)} waiting on a line")

    # The sheet is only as good as what the model was told. Week 2 was built
    # on a schedule file that had Tua Tagovailoa starting for Atlanta while he
    # had not practiced all week, and nothing in the build said so. Now the
    # check runs every time and prints, so a stale input has to be read past
    # rather than discovered afterwards.
    if fact_check:
        report = input_check.check(season, week, game_model.DATA, swaps)
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
    ap.add_argument("--swap", action="append", default=[],
                    metavar='TEAM="QB Name"',
                    help="start this quarterback for TEAM instead of the "
                         "schedule's")
    ap.add_argument("--fact", action="append", default=[],
                    metavar='TEAM="text"',
                    help="sourced note shown under TEAM's game")
    a = ap.parse_args()

    def pairs(items):
        out = []
        for s in items:
            team, _, val = s.partition("=")
            if val:
                out.append((team.strip().upper(), val.strip()))
        return out

    build(a.season, a.week, a.out, a.stars, fact_check=not a.no_check,
          swaps=pairs(a.swap), facts=dict(pairs(a.fact)))
