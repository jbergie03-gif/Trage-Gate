"""Pull the Fantasy Guru subscriber data we are allowed to use, on a leash.

Fantasy Guru has no API. Their support (Rusty, 2026-09-12) said subscribers may
feed the CSV/Excel downloads to a model with one condition: rate limit it.
"once a day or once an hour depending on the data you need ... every 10 minutes
before lock" is fine; constant traffic gets the IP banned. So every run checks a
stamp file first and refuses to hit the site again inside the interval.

    python3 fantasyguru_pull.py                       # once a day, both sets
    python3 fantasyguru_pull.py --dataset props       # props only
    python3 fantasyguru_pull.py --min-interval 600    # Sunday morning cadence
    python3 fantasyguru_pull.py --force               # I know what I am doing

Credentials come from FANTASYGURU_USER / FANTASYGURU_PASS. Downloads land
outside the repo (default ~/fgdata) because it is a paid feed, not our data.

Two sets are worth taking:

  props     /nfl-player-props — every prop market priced at five books plus a
            consensus, which is the one thing nflverse cannot give us.
  rankings  /jeff-mans-nfl-weekly-rankings-ppr — the CSV export button, per
            position. Fantasy ranks, not a betting number.

The stat pages under /data/nfl are Sportradar widgets with no export, so there
is nothing to pull there.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HOME = "https://www.fantasyguru.com"
OUT = os.path.expanduser(os.environ.get("FG_OUT", "~/fgdata"))
DAY = 86400
PACIFIC = datetime.timezone(datetime.timedelta(hours=-7))

# Read one prop market per click. The page swaps the table client-side, so the
# whole sweep is a single page load.
MARKETS = [
    "Rec Yds", "Receptions", "Rush Yds", "Rush Att", "Rush + Rec",
    "Pass Yds", "Pass TDs", "Pass Att", "Completions", "INTs",
    "Long Rec", "Long Rush", "Tackles",
]
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

TABLE_JS = """() => {
  const t = document.querySelector('table');
  if (!t) return null;
  const cell = (r) => [...r.querySelectorAll('th,td')]
      .map((c) => c.innerText.replace(/\\s+/g, ' ').trim());
  const rows = [...t.querySelectorAll('tr')].map(cell);
  return rows.filter((r) => r.length > 1);
}"""


def stamps(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def due(path, dataset, interval):
    """Seconds still to wait before this dataset may be pulled again."""
    last = stamps(path).get(dataset)
    if not last:
        return 0
    waited = time.time() - datetime.datetime.fromisoformat(last).timestamp()
    return max(0, interval - waited)


def mark(path, dataset):
    seen = stamps(path)
    seen[dataset] = datetime.datetime.now(PACIFIC).isoformat(timespec="seconds")
    with open(path, "w") as fh:
        json.dump(seen, fh, indent=2, sort_keys=True)


def login(page):
    """Reuse the stored session when it is still good; log in when it is not."""
    page.goto(HOME + "/account/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if "/account/login" not in page.url:
        return
    user, pw = os.environ.get("FANTASYGURU_USER"), os.environ.get("FANTASYGURU_PASS")
    if not (user and pw):
        sys.exit("set FANTASYGURU_USER and FANTASYGURU_PASS")
    page.fill("#email", user)
    page.fill("#password", pw)
    page.click("button[type=submit]")
    page.wait_for_timeout(6000)
    if "/account/login" in page.url:
        sys.exit("Fantasy Guru rejected the login")


def write(rows, path):
    with open(path, "w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return f"{path} ({len(rows) - 1} rows)"


def props(page, day):
    """Every prop market, all books, one file per market."""
    page.goto(HOME + "/nfl-player-props", wait_until="domcontentloaded")
    page.wait_for_selector("table tbody tr", timeout=60000)
    root = os.path.join(OUT, "props", day)
    os.makedirs(root, exist_ok=True)
    made = []
    for market in MARKETS:
        tab = page.query_selector(f"button:text-is('{market}')")
        if not tab:
            continue
        tab.click()
        page.wait_for_timeout(2500)
        rows = page.evaluate(TABLE_JS)
        if not rows:
            continue
        name = market.lower().replace(" + ", "_").replace(" ", "_")
        made.append(write(rows, os.path.join(root, f"{name}.csv")))
    return made


def rankings(page, day):
    """The CSV export button, once per position."""
    page.goto(HOME + "/jeff-mans-nfl-weekly-rankings-ppr",
              wait_until="domcontentloaded")
    page.wait_for_selector("table tbody tr", timeout=60000)
    # The table paginates at 25, and we read what is rendered.
    page.select_option("select:has(option[value='100'])", "100")
    page.wait_for_timeout(1500)
    root = os.path.join(OUT, "rankings", day)
    os.makedirs(root, exist_ok=True)
    made = []
    for pos in POSITIONS:
        try:
            page.select_option("select:has(option[value=QB])", pos)
        except Exception:
            page.select_option("select >> nth=1", pos)
        page.wait_for_timeout(2000)
        rows = page.evaluate(TABLE_JS)
        if rows:
            made.append(write(rows, os.path.join(root, f"{pos.lower()}.csv")))
    return made


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="props,rankings",
                    help="props, rankings, or both")
    ap.add_argument("--min-interval", type=int, default=DAY,
                    help="seconds between pulls of the same set (default 1 day)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the interval; use sparingly")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    OUT = os.path.expanduser(args.out)
    os.makedirs(OUT, exist_ok=True)
    stamp = os.path.join(OUT, "last_pull.json")

    wanted = [d.strip() for d in args.dataset.split(",") if d.strip()]
    todo = []
    for dataset in wanted:
        wait = 0 if args.force else due(stamp, dataset, args.min_interval)
        if wait:
            print(f"{dataset}: skipped, {wait / 60:.0f} min left on the leash")
        else:
            todo.append(dataset)
    if not todo:
        return

    day = datetime.datetime.now(PACIFIC).strftime("%Y-%m-%d")
    jobs = {"props": props, "rankings": rankings}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            os.path.join(OUT, "browser"), headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        login(page)
        for dataset in todo:
            if dataset not in jobs:
                print(f"{dataset}: no such set")
                continue
            for line in jobs[dataset](page, day):
                print(line)
            mark(stamp, dataset)
        ctx.close()


if __name__ == "__main__":
    main()
