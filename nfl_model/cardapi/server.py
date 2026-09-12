"""Stdlib-only card collector, served next to the pick sheet.

Runs on the same droplet as the scanner, on plain HTTP, and serves the pick
sheet itself from the same origin. Same-origin matters: a page loaded over
HTTPS cannot POST to an HTTP endpoint, so hosting the sheet and the endpoint
together is what removes the copy/paste step without needing a certificate.

Append-only by design: a resubmission lands as a new revision with its own
Pacific timestamp rather than overwriting the previous card. The history is the
point — "the pick was in before kickoff" has to be checkable, not asserted.

No third-party packages, so there is nothing to install and nothing to break
before kickoff.
"""
import datetime
import json
import os
import zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("CARD_DATA_DIR", os.path.join(ROOT, "data"))
CARDS = os.path.join(DATA_DIR, "cards.jsonl")
SHEET = os.environ.get("PICKSHEET", os.path.join(ROOT, "index.html"))
PORT = int(os.environ.get("PORT", "80"))
MAX_BODY = 64 * 1024
MAX_PICKS = 20


def read_cards():
    if not os.path.exists(CARDS):
        return []
    with open(CARDS) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def clean(card):
    """Reject anything that isn't a card, and cap every field's length.

    This endpoint is open to the internet, so it takes only the shape it needs
    and throws away the rest rather than trusting the body.
    """
    if not isinstance(card, dict):
        raise ValueError("body must be a JSON object")
    picks = card.get("picks")
    if not isinstance(picks, list) or not picks:
        raise ValueError("picks must be a non-empty list")
    if len(picks) > MAX_PICKS:
        raise ValueError(f"at most {MAX_PICKS} picks")
    out = []
    for p in picks:
        if not isinstance(p, dict):
            raise ValueError("each pick must be an object")
        out.append({
            "game": str(p.get("game", ""))[:20],
            "side": str(p.get("side", ""))[:20],
            "double": bool(p.get("double", False)),
        })
    return {
        "slate": str(card.get("slate", ""))[:20],
        "who": str(card.get("who", "jonathan"))[:40],
        "picks": out,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "cardapi"

    def _send(self, code, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        slate = (q.get("slate") or [None])[0]
        who = (q.get("who") or ["jonathan"])[0]

        if url.path in ("/", "/index.html"):
            if not os.path.exists(SHEET):
                return self._send(404, {"error": "pick sheet not installed"})
            with open(SHEET, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if url.path == "/health":
            return self._send(200, {"ok": True, "cards": len(read_cards())})
        if url.path == "/cards":
            rows = [r for r in read_cards()
                    if (not slate or r["slate"] == slate) and (not who or r["who"] == who)]
            return self._send(200, {"count": len(rows), "cards": rows})
        if url.path == "/latest":
            if not slate:
                return self._send(400, {"error": "slate is required"})
            rows = [r for r in read_cards() if r["slate"] == slate and r["who"] == who]
            if not rows:
                return self._send(404, {"error": f"no card for {slate} by {who}"})
            return self._send(200, {"revisions": len(rows), "card": rows[-1]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/card":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if length <= 0 or length > MAX_BODY:
            return self._send(400, {"error": "body must be 1 byte to 64 KiB"})
        try:
            card = clean(json.loads(self.rfile.read(length)))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})

        row = {"submitted_at_pt": datetime.datetime.now(PACIFIC).isoformat(timespec="seconds"), **card}
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CARDS, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        revisions = len([r for r in read_cards()
                         if r["slate"] == row["slate"] and r["who"] == row["who"]])
        return self._send(200, {
            "ok": True,
            "submitted_at_pt": row["submitted_at_pt"],
            "picks": len(row["picks"]),
            "revisions": revisions,
        })

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"serving pick sheet + card API on :{PORT}, data in {DATA_DIR}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
