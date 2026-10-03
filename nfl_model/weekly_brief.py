"""Gather everything the Saturday brief reads into one markdown file.

Saturday morning Jonathan wants one message: what the model says about every
game, what Fantasy Guru wrote this week, and how both touch his Yahoo roster
and his FanDuel lineups. The pulls already exist (odds_snapshot.py,
fantasyguru_pull.py, picksheet_build.py); this just runs them in order and
writes the inputs side by side so the summary is written from files, not from
memory.

    python3 weekly_brief.py                      # next slate, all pulls
    python3 weekly_brief.py --no-pull            # re-read what is on disk
    python3 weekly_brief.py --roster ~/memory/yahoo-fantasy-team.md

Output: ~/fgdata/brief/<season>-w<week>.md (or --out). Nothing here is a
recommendation; the labels are the reader's job. The model section carries the
same coin-flip / error-bar notes as the pick sheet, and the Fantasy Guru
section is their text, quoted, so it stays marked as a media claim.
"""
import argparse
import datetime
import glob
import os
import re
import subprocess

import pandas as pd

import fantasyguru_pull as fg
import game_model
import input_check
import picksheet_build

HERE = os.path.dirname(os.path.abspath(__file__))
PACIFIC = fg.PACIFIC


def run(cmd, env=None):
    """Run a pull, keep going when it fails, and say so in the brief."""
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=HERE, text=True, capture_output=True,
                       env={**os.environ, **(env or {})})
    tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
    return r.returncode, tail


def pulls(season, week):
    L = ["## Pulls"]
    steps = [
        ["bash", "fetch_data.sh"],
        ["python3", "odds_snapshot.py"],
        ["python3", "fantasyguru_pull.py", "--season", str(season),
         "--week", str(week)],
    ]
    for cmd in steps:
        code, tail = run(cmd)
        L.append(f"- `{' '.join(cmd)}` -> exit {code}")
        L += [f"    {t}" for t in tail]
    return L


def model_section(df, season, week):
    games, stamp = picksheet_build.rows(df, season, week)
    L = [f"## Model vs DraftKings ({stamp or 'no DK snapshot'})",
         "", "| Game | Kick | Line | Total | Model pick | Note | Model total | O/U note |",
         "|---|---|---|---|---|---|---|---|"]
    for g in games:
        star = " **x2**" if g.get("devinDouble") else ""
        L.append(f"| {g['away']} @ {g['home']} | {g['kick']} | {g['spread']} | "
                 f"{g['total']} | {g['devin']}{star} | {g['devinNote']} | "
                 f"{g.get('modelTotal', '')} | {g.get('totalNote', '')} |")
    L += ["", "Spread model is scored flat; totals model has no demonstrated "
          "O/U edge (49% historically) — totals are leans, not plays."]
    return L


def check_section(season, week):
    try:
        return ["## Input check (QB assumptions, injuries the model saw)", ""] + \
            input_check.check(season, week, game_model.DATA)
    except Exception as e:  # the brief is still useful without it
        return ["## Input check", f"failed: {e}"]


def latest(sub):
    days = sorted(d for d in glob.glob(os.path.join(fg.OUT, sub, "*"))
                  if os.path.isdir(d))
    return days[-1] if days else None


def rankings_section(roster):
    day = latest("rankings")
    L = [f"## Fantasy Guru rankings ({os.path.basename(day) if day else 'none'})"]
    if not day:
        return L
    frames = []
    for path in glob.glob(os.path.join(day, "*.csv")):
        try:
            d = pd.read_csv(path)
        except Exception:
            continue
        d["pos"] = os.path.basename(path)[:-4].upper()
        frames.append(d)
    if not frames:
        return L + ["no readable files"]
    allr = pd.concat(frames, ignore_index=True)
    name_col = next((c for c in allr.columns
                     if c.lower() in ("player", "name")), allr.columns[0])
    rank_col = next((c for c in allr.columns
                     if c.lower() in ("rank", "rk", "#")), None)
    if roster:
        L += ["", "| Roster player | Pos | FG rank |", "|---|---|---|"]
        for name in roster:
            hit = allr[allr[name_col].astype(str).str.contains(
                re.escape(name.split()[-1]), case=False, na=False)
                & allr[name_col].astype(str).str.contains(
                re.escape(name.split()[0][:3]), case=False, na=False)]
            if hit.empty:
                L.append(f"| {name} | – | not ranked |")
            else:
                r = hit.iloc[0]
                L.append(f"| {name} | {r['pos']} | "
                         f"{r[rank_col] if rank_col else '?'} |")
    L += ["", f"full files: {day}"]
    return L


def smash_section():
    day = latest("smash")
    L = [f"## SMASH ({os.path.basename(day) if day else 'none'}) — measured, not applied"]
    if not day:
        return L
    path = os.path.join(day, "matchups.csv")
    if os.path.exists(path):
        d = pd.read_csv(path)
        num = [c for c in d.columns if d[c].dtype != object]
        if num:
            col = num[-1]
            d = d.reindex(d[col].abs().sort_values(ascending=False).index)
            L += ["", "| " + " | ".join(d.columns) + " |",
                  "|" + "---|" * len(d.columns)]
            L += ["| " + " | ".join(str(v) for v in r) + " |"
                  for r in d.head(8).itertuples(index=False)]
    L += ["", f"files: {day}"]
    return L


def articles_section():
    day = latest("articles")
    L = [f"## Fantasy Guru articles ({os.path.basename(day) if day else 'none'})"]
    if not day:
        return L
    for path in sorted(glob.glob(os.path.join(day, "*.txt"))):
        with open(path) as fh:
            title = fh.readline().strip()
            fh.readline()
            body = fh.read()
        L.append(f"- **{title}** — {len(body)} chars — `{path}`")
    L += ["", "Read the start/sit, injury report, cash breakdown, Marlin's "
          "betting column and game scripts in full before writing the brief; "
          "quote them as Fantasy Guru claims (UNV) until checked elsewhere."]
    return L


def roster_names(path):
    if not path or not os.path.exists(path):
        return []
    names = []
    for line in open(path):
        m = re.match(r"\|\s*[A-Z/]+\s*\|\s*([A-Za-z.' -]+?)\s*[(|]", line)
        if m and m.group(1).lower() != "player":
            names.append(m.group(1))
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--roster", default=os.path.expanduser(
        "~/memory/yahoo-fantasy-team.md"))
    ap.add_argument("--out")
    a = ap.parse_args()

    df = game_model.build(*game_model.load())
    season, week = a.season, a.week
    if season is None or week is None:
        season, week = game_model.next_slate(df)
    now = datetime.datetime.now(PACIFIC).strftime("%Y-%m-%d %H:%M PT")
    L = [f"# Saturday brief — {season} week {week}", f"built {now}", ""]
    if not a.no_pull:
        L += pulls(season, week) + [""]
        df = game_model.build(*game_model.load())
    L += model_section(df, season, week) + [""]
    L += check_section(season, week) + [""]
    L += rankings_section(roster_names(a.roster)) + [""]
    L += smash_section() + [""]
    L += articles_section()

    out = a.out or os.path.join(fg.OUT, "brief", f"{season}-w{week:02d}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(out)


if __name__ == "__main__":
    main()
