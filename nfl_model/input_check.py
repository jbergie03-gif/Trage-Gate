"""Fact-check the model's inputs before a sheet is published.

The model is a calculator: it cannot read a headline, and it will happily
produce a confident number from a stale fact. Week 2 showed the failure mode --
the schedule feed listed Tua Tagovailoa as Atlanta's starter, the model priced
Atlanta as though that were settled, and in reality he had not practiced all
week. The prediction was not wrong because the math was wrong. It was wrong
because an input was.

So this checks the inputs, not the output. For one upcoming slate it prints,
per game, what the model believes and how sure that belief is:

* the announced starting quarterback, and whether the injury report contradicts
  it (listed Out/Doubtful/Questionable, or did not practice),
* whether that starter differs from whoever actually took the snaps in the
  team's last game,
* whether the model has enough career dropbacks on him to rate him at all,
* how much of the injury report the model is actually carrying, since a feed
  that has not published designations yet leaves every team looking healthy,
* and for every quarterback it flags, what the prediction becomes if the most
  likely replacement starts instead.

That last one is the point. A flag with no number attached invites a guess; a
flag that says "this pick moves 1.8 points" is a decision. Nothing here edits a
published card -- it reports, and a human decides.

Usage:
    python3 input_check.py --season 2026 --week 2
    python3 input_check.py --season 2026 --week 2 --out check.md
    python3 input_check.py --season 2026 --week 2 --swap ATL="Cooper Rush"
"""
import argparse
import datetime as dt
import os
import zoneinfo

import pandas as pd

import game_model

PT = zoneinfo.ZoneInfo("America/Los_Angeles")

# Designations, worst first. Questionable is included even though most
# Questionable players suit up: the model treats the announced starter as a
# certainty, so any designation at all is a gap between belief and fact.
SEVERITY = ["Out", "Doubtful", "Questionable"]
DNP = "Did Not Participate In Practice"
LIMITED = "Limited Participation in Practice"

# Below this many career dropbacks the model's own `qb_new_*` flag fires and it
# stops trusting the quarterback's rating. Same constant the feature uses.
NEW_QB_DROPBACKS = 200


def age(path):
    """Hours since a data file was last written, or None if it is missing."""
    if not os.path.exists(path):
        return None
    delta = dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(path))
    return delta.total_seconds() / 3600


def read_injuries(data, season):
    for ext in (".csv.gz", ".csv"):
        path = os.path.join(data, f"inj_{season}{ext}")
        if os.path.exists(path):
            return pd.read_csv(path, low_memory=False), path
    return pd.DataFrame(), None


def designation(row):
    """One phrase for what the report says about a player, worst part first."""
    status = row.get("report_status")
    practice = row.get("practice_status")
    bits = []
    if isinstance(status, str) and status in SEVERITY:
        bits.append(status)
    if practice == DNP:
        bits.append("did not practice")
    elif practice == LIMITED:
        bits.append("limited in practice")
    injury = row.get("report_primary_injury")
    if not isinstance(injury, str):
        injury = row.get("practice_primary_injury")
    if isinstance(injury, str):
        bits.append(injury.lower())
    return ", ".join(bits)


def rank(row):
    """How much a designation should worry us, 3 = Out, 0 = nothing said."""
    status = row.get("report_status")
    if isinstance(status, str) and status in SEVERITY:
        return 3 - SEVERITY.index(status)
    return 1 if row.get("practice_status") == DNP else 0


def last_starters(tg, season):
    """team -> (week, qb_id, qb_name) for the most recent game actually played.

    Taken from the team-game table rather than the schedule, so this is who
    threw the passes, not who was announced.
    """
    played = tg[tg["season"] == season].sort_values("week")
    out = {}
    for r in played.itertuples():
        if isinstance(r.qb_id, str):
            out[r.team] = (r.week, r.qb_id, r.qb_name)
    return out


def roster_qbs(players, team):
    """Quarterbacks the player feed currently has on a team's roster."""
    q = players[(players["latest_team"] == team)
                & (players["position"] == "QB")
                & players["gsis_id"].notna()]
    return list(zip(q["gsis_id"], q["display_name"]))


def replacement(players, ratings, team, exclude, unavailable):
    """The most likely next man up: most career dropbacks, not ruled out.

    Career dropbacks is a blunt proxy for a depth chart, but it is a number in
    the data rather than a guess, and it gets the common case right -- the
    veteran backup outranks the rookie third-stringer.
    """
    best = None
    for qb_id, name in roster_qbs(players, team):
        if qb_id == exclude or qb_id in unavailable:
            continue
        db = ratings.qb_seen(qb_id)
        if best is None or db > best[2]:
            best = (qb_id, name, db)
    return best


def fitted(df):
    """Fit the margin model once, on every completed game."""
    done = df[df["result"].notna() & df["spread_line"].notna()
              & df["total_line"].notna()]
    return game_model.ridge().fit(done[game_model.FEATURES].values,
                                  done["result"].values)


def repredict(model, row, ratings, side, qb_id):
    """Predicted home margin if `side` starts `qb_id` instead.

    Only two features move: the quarterback rating difference and the
    inexperience flag for that side. Everything else about the game -- the
    efficiency ratings, the travel, the weather -- is unchanged by who lines up
    at quarterback, so the row is edited rather than the league replayed.
    """
    r = row.copy()
    other = "away" if side == "home" else "home"
    keep = r[f"qb_{other}_rating"]
    new = ratings.qb_rating(qb_id)
    r["qb_diff"] = (new - keep) if side == "home" else (keep - new)
    r[f"qb_new_{side}"] = 1 if ratings.qb_seen(qb_id) < NEW_QB_DROPBACKS else 0
    x = [[r[f] for f in game_model.FEATURES]]
    return float(model.predict(x)[0])


def check(season, week, data, swaps=None):
    """Everything the report needs, as a list of markdown lines."""
    games_csv = os.path.join(data, "games.csv")
    g, tg, inj_burden = game_model.load()
    df, ratings = game_model.build(g, tg, inj_burden, with_ratings=True)
    model = fitted(df)

    up = df[(df["season"] == season) & (df["week"] == week)].copy()
    if up.empty:
        return [f"no games found for {season} week {week}"]

    sched = g[(g["season"] == season) & (g["week"] == week)]
    qb_of = {}
    for r in sched.itertuples():
        qb_of[(r.home_team, "home")] = (r.home_qb_id, r.home_qb_name)
        qb_of[(r.away_team, "away")] = (r.away_qb_id, r.away_qb_name)

    # Ratings for both sides, cached on the row so a swap can keep one side.
    for side in ("home", "away"):
        up[f"qb_{side}_id"] = up[f"{side}_team"].map(
            lambda t, s=side: qb_of.get((t, s), (None, None))[0])
        up[f"qb_{side}_name"] = up[f"{side}_team"].map(
            lambda t, s=side: qb_of.get((t, s), (None, None))[1])
        up[f"qb_{side}_rating"] = up[f"qb_{side}_id"].map(ratings.qb_rating)

    up["pred_margin"] = model.predict(up[game_model.FEATURES].values)

    inj, inj_path = read_injuries(data, season)
    this_week = inj[inj["week"] == week] if len(inj) else pd.DataFrame()
    reported = {}
    for r in this_week.to_dict("records"):
        gid = r.get("gsis_id")
        if isinstance(gid, str):
            reported[gid] = r
    ruled_out = {gid for gid, r in reported.items()
                 if r.get("report_status") == "Out"}

    players = pd.read_csv(os.path.join(data, "players.csv"), low_memory=False)
    recent = last_starters(tg, season)

    L = [f"# Input check — {season} week {week}",
         f"_run {dt.datetime.now(PT):%Y-%m-%d %H:%M PT}_", ""]

    # ---- 1. is the data even current -------------------------------------
    L += ["## Feed freshness", ""]
    for label, path in [("schedule + announced starters", games_csv),
                        ("injury report", inj_path),
                        ("injury burden the model uses",
                         os.path.join(data, "injury_burden.csv"))]:
        hours = age(path) if path else None
        L.append(f"- {label}: "
                 + ("**missing**" if hours is None else f"{hours:.0f}h old"))

    designated = int(this_week["report_status"].isin(SEVERITY).sum()) \
        if len(this_week) else 0
    L += ["", f"- injury report rows for week {week}: **{len(this_week)}**, "
              f"of which **{designated}** carry an Out/Doubtful/Questionable "
              f"designation"]
    if designated == 0:
        L.append("- **the model is pricing all 32 teams as fully healthy.** "
                 "Designations are not published until Friday, so its three "
                 "injury features are zero for every game on this slate.")
    L.append("")

    # ---- 2. quarterback by quarterback -----------------------------------
    L += ["## Quarterbacks the model is assuming", ""]
    flags = []
    for r in up.sort_values("gameday").itertuples():
        for side in ("home", "away"):
            team = getattr(r, f"{side}_team")
            qb_id = getattr(r, f"qb_{side}_id")
            name = getattr(r, f"qb_{side}_name")
            notes = []
            level = 0

            rep = reported.get(qb_id)
            if rep:
                phrase = designation(rep)
                if phrase:
                    notes.append(f"injury report says **{phrase}**")
                    level = max(level, rank(rep))

            was = recent.get(team)
            if was and isinstance(qb_id, str) and was[1] != qb_id:
                notes.append(f"did not start week {was[0]} — {was[2]} did")
                level = max(level, 2)

            db = ratings.qb_seen(qb_id)
            if db < NEW_QB_DROPBACKS:
                notes.append(f"only {db:.0f} career dropbacks, so the model "
                             f"discounts his rating")
                level = max(level, 1)

            if notes:
                flags.append((level, r, side, team, qb_id, name, notes))

    if not flags:
        L.append("Nothing on the injury report or the depth chart contradicts "
                 "the announced starter in any game.")
    else:
        L.append("| Game | Team | Model assumes | Problem |")
        L.append("|---|---|---|---|")
        for level, r, side, team, qb_id, name, notes in sorted(
                flags, key=lambda f: -f[0]):
            mark = "**" if level >= 2 else ""
            L.append(f"| {r.away_team} @ {r.home_team} | {team} | "
                     f"{mark}{name}{mark} | {'; '.join(notes)} |")
    L.append("")

    # ---- 3. what each flag is worth in points ----------------------------
    serious = [f for f in flags if f[0] >= 2]
    if serious:
        L += ["## What the flags are worth", "",
              "Each row re-runs the model with the most likely replacement "
              "(most career dropbacks on the roster who is not ruled out) and "
              "shows how far the pick moves. A published card is **not** "
              "changed by this.", "",
              "| Game | If instead | Model now | Model then | Line | "
              "Edge now | Edge then |", "|---|---|---|---:|---:|---:|---:|"]
        for level, r, side, team, qb_id, name, _ in sorted(
                serious, key=lambda f: -f[0]):
            alt = replacement(players, ratings, team, qb_id, ruled_out)
            if alt is None:
                continue
            row = up[up["game_id"] == r.game_id].iloc[0]
            then = repredict(model, row, ratings, side, alt[0])
            sign = 1 if side == "home" else -1
            L.append(
                f"| {r.away_team} @ {r.home_team} | {alt[1]} ({alt[2]:.0f} "
                f"career dropbacks) | {r.pred_margin:+.1f} | {then:+.1f} | "
                f"{r.spread_line:+.1f} | "
                f"{sign * (r.pred_margin - r.spread_line):+.1f} | "
                f"{sign * (then - r.spread_line):+.1f} |")
        L += ["", "Margins are the home team's. Edges are signed for the team "
                  "in the flagged column, so a shrinking edge means the model "
                  "likes that side less.", ""]

    # ---- 4. explicit what-ifs asked for on the command line --------------
    for team, who in (swaps or {}):
        hit = players[(players["position"] == "QB")
                      & (players["display_name"].str.lower() == who.lower())]
        if hit.empty:
            L.append(f"- could not find a quarterback named {who}")
            continue
        qb_id = hit.iloc[0]["gsis_id"]
        rows = up[(up["home_team"] == team) | (up["away_team"] == team)]
        for row in rows.to_dict("records"):
            side = "home" if row["home_team"] == team else "away"
            then = repredict(model, pd.Series(row), ratings, side, qb_id)
            L += ["## Asked what-if", "",
                  f"- {row['away_team']} @ {row['home_team']} with {who} at "
                  f"{team}: home margin {row['pred_margin']:+.1f} → "
                  f"**{then:+.1f}** against a line of "
                  f"{row['spread_line']:+.1f}", ""]

    L += ["## What this cannot check", "",
          "- Coaching, scheme and locker-room news. None of it is a number in "
          "the feed, and there is no historical version of it to test against, "
          "so it stays out of the model rather than being guessed at.",
          "- Whether a Questionable player actually plays. That is Sunday "
          "morning information.",
          "- Weather. The model reads a game-time observation historically and "
          "a blank for an upcoming game, which is its own known gap.", ""]
    return L


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--week", type=int, required=True)
    p.add_argument("--data", default=game_model.DATA)
    p.add_argument("--out", help="also write the report to this file")
    p.add_argument("--swap", action="append", default=[],
                   metavar="TEAM=QB NAME",
                   help="re-run one game with a different starter")
    a = p.parse_args()

    swaps = []
    for s in a.swap:
        team, _, who = s.partition("=")
        if who:
            swaps.append((team.strip().upper(), who.strip()))

    lines = check(a.season, a.week, a.data, swaps)
    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
