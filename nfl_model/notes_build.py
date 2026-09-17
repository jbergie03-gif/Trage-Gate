"""Render a week's scouting notes to a standalone page.

The model is a calculator and it reads none of this: a note here never moves a
pick, and the file it renders is written by hand after reading the week's
reporting. What the notes are for is the half of a game the features cannot
hold -- who was ruled out on Friday, which coach will not name a starter, what
the market is reacting to -- kept next to the model's number rather than
blended into it.

So the format is deliberately rigid. Every line is labelled, and the labels are
the ones that matter when a reader has to decide what to trust:

    ## CAR @ ATL — Sun 10:00 AM PT
    model: ATL by 5.1
    line: CAR -2.5
    pick: ATL +2.5 — double
    fact: Tua Tagovailoa did not practise Wednesday (oblique).
    unknown: Stefanski will not name a starter.
    read: The model's biggest edge of the week rests on that unknown.

`fact` is something published and checkable. `unknown` is something nobody
knows yet, written down so it cannot be quietly turned into a fact later.
`read` is opinion, and it is labelled opinion. A note with a read but no fact
is the failure mode this format exists to prevent.

Run: python3 notes_build.py notes/2026-w02.md [--out notes/2026-w02.html]
"""
import argparse
import html
import os
import re

KEYS = ("model", "line", "pick", "fact", "unknown", "read")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg:#0f1115; --card:#181b22; --line:#262b36; --text:#e8eaed;
    --dim:#9aa0ac; --fact:#3fb950; --unknown:#d9a20b; --model:#a371f7;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:20px 12px 60px; background:var(--bg);
    color:var(--text);
    font:16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  header, main, footer {{ max-width:680px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 6px; }}
  .sub {{ color:var(--dim); font-size:13px; margin-bottom:20px; }}
  .game {{ background:var(--card); border:1px solid var(--line);
    border-radius:12px; padding:14px 16px; margin-bottom:12px; }}
  .head {{ display:flex; justify-content:space-between; align-items:baseline;
    gap:10px; margin-bottom:10px; }}
  .match {{ font-size:17px; font-weight:700; }}
  .kick {{ color:var(--dim); font-size:12px; white-space:nowrap; }}
  .nums {{ display:flex; flex-wrap:wrap; gap:6px 18px; font-size:13px;
    color:var(--dim); margin-bottom:10px; }}
  .nums b {{ color:var(--text); font-weight:600; }}
  .pick {{ color:var(--model); font-weight:700; }}
  .note {{ display:flex; gap:8px; margin:7px 0; font-size:14.5px; }}
  .tag {{ flex:none; font-size:10px; font-weight:700; letter-spacing:.05em;
    padding:3px 6px; border-radius:5px; height:fit-content; margin-top:2px; }}
  .tag.fact {{ background:#123a1c; color:var(--fact); }}
  .tag.unknown {{ background:#3a2d08; color:var(--unknown); }}
  .tag.read {{ background:#241a38; color:var(--model); }}
  footer {{ color:var(--dim); font-size:12.5px; border-top:1px solid var(--line);
    margin-top:24px; padding-top:14px; }}
  a {{ color:#58a6ff; }}
</style>
</head>
<body>
<header><h1>{title}</h1><div class="sub">{sub}</div></header>
<main>
{games}
</main>
<footer>{footer}</footer>
</body>
</html>
"""

GAME = """<section class="game">
  <div class="head"><div class="match">{match}</div>
    <div class="kick">{kick}</div></div>
  <div class="nums">{nums}</div>
  {notes}
</section>"""


def parse(text):
    """Split the markdown into a header block and one dict per game."""
    head, games, cur = {}, [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            match, _, kick = line[3:].partition("—")
            cur = dict(match=match.strip(), kick=kick.strip(), notes=[])
            games.append(cur)
            continue
        m = re.match(r"(\w+):\s*(.+)", line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        target = cur if cur is not None else head
        if key in ("fact", "unknown", "read"):
            target["notes"].append((key, val)) if cur is not None \
                else head.setdefault(key, val)
        elif key in KEYS or cur is None:
            target[key] = val
    return head, games


def render(text):
    head, games = parse(text)
    blocks = []
    for g in games:
        nums = []
        if g.get("model"):
            nums.append(f"model <b>{html.escape(g['model'])}</b>")
        if g.get("line"):
            nums.append(f"line <b>{html.escape(g['line'])}</b>")
        if g.get("pick"):
            nums.append(f'<span class="pick">{html.escape(g["pick"])}</span>')
        notes = "\n  ".join(
            f'<div class="note"><span class="tag {k}">{k.upper()}</span>'
            f"<span>{html.escape(v)}</span></div>" for k, v in g["notes"])
        blocks.append(GAME.format(match=html.escape(g["match"]),
                                  kick=html.escape(g["kick"]),
                                  nums=" ".join(nums), notes=notes))
    return PAGE.format(title=html.escape(head.get("title", "Scouting notes")),
                       sub=html.escape(head.get("sub", "")),
                       footer=html.escape(head.get("footer", "")),
                       games="\n".join(blocks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="the week's notes markdown")
    ap.add_argument("--out", help="defaults to the source with .html")
    a = ap.parse_args()

    with open(a.source) as fh:
        text = fh.read()
    out = a.out or os.path.splitext(a.source)[0] + ".html"
    page = render(text)
    with open(out, "w") as fh:
        fh.write(page)
    _, games = parse(text)
    facts = sum(1 for g in games for k, _ in g["notes"] if k == "fact")
    unknowns = sum(1 for g in games for k, _ in g["notes"] if k == "unknown")
    print(f"wrote {out}: {len(games)} games, {facts} facts, "
          f"{unknowns} open questions")


if __name__ == "__main__":
    main()
