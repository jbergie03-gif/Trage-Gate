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

A game may also carry a `caption:` line: the same game said in one sentence,
for the Instagram post that sends people to the page. `--caption` collects
those into a caption file with the header's `lead` and `tail` around them, and
refuses to write one that Instagram would truncate or that carries a link,
since a caption cannot be clicked.

Run: python3 notes_build.py notes/2026-w02.md [--out notes/2026-w02.html]
"""
import argparse
import html
import os
import re

KEYS = ("model", "line", "pick", "fact", "unknown", "read", "caption")
CAPTION_MAX = 2200
# Case-insensitive: a shouted URL is the same dead text as a quiet one. The
# dotted quad is here because the site spent its first weeks on a bare IP,
# which reads as a number rather than a link and slipped the other patterns.
LINK = re.compile(r"https?://|www\.|\.(?:com|net|org|io|co)\b"
                  r"|\b\d{1,3}(?:\.\d{1,3}){3}\b", re.I)

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
  nav {{ max-width:680px; margin:0 auto 16px; font-size:13px; }}
  nav a {{ margin-right:14px; }}
</style>
</head>
<body>
<header><h1>{title}</h1><div class="sub">{sub}</div></header>
<nav><a href="/week">This week's numbers</a><a href="/">Pick sheet</a></nav>
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
        if cur is None and key in ("lead", "tail"):
            # Repeatable: a caption reads as paragraphs, and one physical line
            # per paragraph keeps the source diffable.
            head.setdefault(key, []).append(val)
        elif key in ("fact", "unknown", "read"):
            target["notes"].append((key, val)) if cur is not None \
                else head.setdefault(key, val)
        elif key in KEYS or cur is None:
            target[key] = val
    return head, games


def caption(text):
    """The week in one post: the header's lead, a line per flagged game, the tail.

    Instagram captions cannot be clicked, so a link here is dead text that
    still costs characters -- the page is reached through the profile link and
    the caption only has to say that.
    """
    head, games = parse(text)
    lines = list(head.get("lead", []))
    lines += [f"{g['match']} — {g['caption']}"
              for g in games if g.get("caption")]
    lines += head.get("tail", [])
    out = "\n\n".join(lines) + "\n"
    if len(out) > CAPTION_MAX:
        raise ValueError(f"caption is {len(out)} characters, Instagram cuts "
                         f"at {CAPTION_MAX}")
    bad = LINK.search(out)
    if bad:
        raise ValueError(f"caption contains {bad.group(0)!r}: a caption link "
                         "is not clickable, point at the profile link instead")
    return out


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
    ap.add_argument("--caption", action="store_true",
                    help="also write the Instagram caption as .txt")
    a = ap.parse_args()

    with open(a.source) as fh:
        text = fh.read()
    stem = os.path.splitext(a.source)[0]
    out = a.out or stem + ".html"
    # Both outputs are built before either is written, so a caption the guards
    # refuse does not leave a half-published week on disk.
    page = render(text)
    body = None
    if a.caption:
        try:
            body = caption(text)
        except ValueError as e:
            raise SystemExit(f"caption: {e}")
    with open(out, "w") as fh:
        fh.write(page)
    if body is not None:
        with open(stem + ".txt", "w") as fh:
            fh.write(body)
        print(f"wrote {stem}.txt: {len(body)} of {CAPTION_MAX} characters")
    _, games = parse(text)
    facts = sum(1 for g in games for k, _ in g["notes"] if k == "fact")
    unknowns = sum(1 for g in games for k, _ in g["notes"] if k == "unknown")
    print(f"wrote {out}: {len(games)} games, {facts} facts, "
          f"{unknowns} open questions")


if __name__ == "__main__":
    main()
