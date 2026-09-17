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
import hmac
import json
import os
import re
import secrets
import threading
import time
import zoneinfo
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("CARD_DATA_DIR", os.path.join(ROOT, "data"))
CARDS = os.path.join(DATA_DIR, "cards.jsonl")
SUBS = os.path.join(DATA_DIR, "subscribers.jsonl")
SECRET_FILE = os.path.join(DATA_DIR, "subscriber_secret")
SHEET = os.environ.get("PICKSHEET", os.path.join(ROOT, "index.html"))
# Kickoff times for the sheet's slate, written beside it by picksheet_build.
# The card is only worth anything if the pick was in before kickoff, and the
# page cannot be the thing that guarantees that: its lock is JavaScript over
# editable localStorage, and /card is a plain POST anyone can replay.
KICKOFFS = os.environ.get("KICKOFFS", os.path.join(ROOT, "kickoffs.json"))
# The published week page, uploaded by weekly_post.py. Served rather than
# generated: fitting the model needs ~520 MB and the box has 458 MB.
WEEK = os.environ.get("WEEKPAGE", os.path.join(ROOT, "week.html"))
# The week's hand-written scouting notes, rendered by notes_build.py. Served
# beside the sheet rather than merged into it: the sheet is what the model
# says, and these are the things it cannot read.
NOTES = os.environ.get("NOTESPAGE", os.path.join(ROOT, "notes.html"))
PORT = int(os.environ.get("PORT", "80"))
# Behind Caddy on the droplet, so it binds loopback there and the certificate
# terminates in front of it. Default stays public for running it bare.
HOST = os.environ.get("HOST", "0.0.0.0")
MAX_BODY = 64 * 1024
MAX_PICKS = 20
# Deliberately loose: the only address format worth rejecting is one that
# cannot be sent to at all. Anything stricter bounces real addresses, and the
# real confirmation that an address works is the first delivery.
EMAIL = re.compile(r"^[^@\s,;<>]{1,64}@[^@\s,;<>.]+(\.[^@\s,;<>.]+)+$")
SIGNUP_LIMIT = 20          # per IP
SIGNUP_WINDOW = 3600       # seconds


def read_cards():
    if not os.path.exists(CARDS):
        return []
    with open(CARDS) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def kickoffs():
    """{slate: {"AWAY@HOME": kickoff}}, or {} when the file is missing.

    Missing means unenforced rather than closed: an old sheet whose slate has
    no entry still submits. Read per request so a redeployed sheet takes
    effect without a restart, same as the week page.
    """
    try:
        with open(KICKOFFS) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    out = {}
    for slate, games in raw.items():
        out[slate] = {g: datetime.datetime.fromisoformat(t)
                      for g, t in games.items()}
    return out


def too_late(card):
    """Games on the card that had already started. Empty is the good case."""
    games = kickoffs().get(card["slate"], {})
    if not games:
        return []
    now = datetime.datetime.now(PACIFIC)
    return [p["game"] for p in card["picks"]
            if p["game"] in games and games[p["game"]] <= now]


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
        # Canonical "AWAY@HOME": "NE @ SEA" is the same game, and if it is
        # stored differently it dodges the kickoff check and reads as a
        # separate game when the card is scored.
        game = re.sub(r"\s+", "", str(p.get("game", "")))[:20]
        side = str(p.get("side", ""))[:20].strip()
        teams = game.split("@")
        if side and len(teams) == 2 and side.split(" ")[0] not in teams:
            raise ValueError(f"{side!r} is not a team in {game}")
        out.append({"game": game, "side": side,
                    "double": bool(p.get("double", False))})
    return {
        "slate": str(card.get("slate", ""))[:20],
        "who": str(card.get("who", "jonathan"))[:40],
        "picks": out,
    }


_lock = threading.Lock()
_hits = {}


def secret():
    """Per-box key for unsubscribe tokens, created on first use.

    Kept in the data dir rather than the environment so the tokens in already
    delivered emails keep working across a restart or a redeploy — an
    unsubscribe link that stops working is the CAN-SPAM violation.
    """
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as fh:
            return fh.read().strip().encode()
    os.makedirs(DATA_DIR, exist_ok=True)
    key = secrets.token_urlsafe(32)
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with open(fd, "w") as fh:
        fh.write(key)
    return key.encode()


def token(email):
    """Unsubscribe token: derived, not stored, so it cannot drift out of sync.

    Signed with the box key, so a token for one address says nothing about any
    other and nobody can unsubscribe a stranger by guessing.
    """
    return hmac.new(secret(), email.encode(), sha256).hexdigest()[:32]


def clean_email(raw):
    email = str(raw or "").strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise ValueError("that does not look like an email address")
    return email


def read_subs():
    if not os.path.exists(SUBS):
        return []
    with open(SUBS) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def subscriber_state():
    """Current list, from the append-only log: last event per address wins.

    Unsubscribes are recorded rather than deleted so that a later resubscribe
    is visible as its own event instead of looking like the first one.
    """
    state = {}
    for row in read_subs():
        state[row["email"]] = row
    return state


def log_sub(email, event, source=""):
    row = {
        "at_pt": datetime.datetime.now(PACIFIC).isoformat(timespec="seconds"),
        "email": email,
        "event": event,
        "source": source[:40],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with _lock:
        with open(SUBS, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        try:
            os.chmod(SUBS, 0o600)
        except OSError:
            pass
    return row


def rate_limited(ip):
    """Cheap per-IP cap on signups. Open endpoint on a 512 MB box: the point
    is to keep a script from filling the disk, not to stop a determined flood.
    """
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(ip, []) if now - t < SIGNUP_WINDOW]
        hits.append(now)
        _hits[ip] = hits
        if len(_hits) > 5000:
            _hits.clear()
        return len(hits) > SIGNUP_LIMIT


def page(title, body):
    return (f"<!doctype html><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title>"
            f"<style>body{{background:#0d1117;color:#e6edf3;font:16px/1.6 "
            f"-apple-system,Segoe UI,Roboto,sans-serif;margin:0;display:flex;"
            f"min-height:100vh;align-items:center;justify-content:center;"
            f"padding:24px}}div{{max-width:32rem;text-align:center}}"
            f"h1{{font-size:1.4rem;margin:0 0 .6rem}}"
            f"p{{color:#9aa7b4;margin:.4rem 0}}"
            f"a{{color:#7c8cff}}</style>"
            f"<div><h1>{title}</h1>{body}</div>").encode()


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
        if url.path in ("/week", "/week.html"):
            if not os.path.exists(WEEK):
                return self._send(404, {"error": "no week page published"})
            with open(WEEK, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if url.path in ("/notes", "/notes.html"):
            if not os.path.exists(NOTES):
                # Linked from the week page, so a reader can land here before
                # the week's notes are written: say so in a page rather than
                # answering a person with JSON.
                return self._send(404, page(
                    "No notes yet this week",
                    "<p>This week's notes are not written yet. The numbers "
                    "are already up.</p><p><a href='/week'>This week's "
                    "numbers</a></p>"), "text/html; charset=utf-8")
            with open(NOTES, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if url.path == "/health":
            live = [r for r in subscriber_state().values()
                    if r["event"] == "subscribe"]
            return self._send(200, {"ok": True, "cards": len(read_cards()),
                                    "subscribers": len(live)})
        if url.path == "/unsubscribe":
            return self._unsubscribe(q)
        if url.path == "/subscribers":
            return self._subscribers()
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

    def _unsubscribe(self, q):
        """One click, no login, no confirmation step.

        Required to work from a link in an email, which means it has to work
        for someone who is not logged in and will not fill in a form.
        """
        email = (q.get("e") or [""])[0].strip().lower()
        given = (q.get("t") or [""])[0]
        if not email or not given:
            return self._send(400, page(
                "Link incomplete",
                "<p>Use the unsubscribe link from the bottom of the email, or "
                "reply to it and you will be removed by hand.</p>"),
                "text/html; charset=utf-8")
        if not hmac.compare_digest(token(email), given):
            return self._send(400, page(
                "Link not recognized",
                "<p>Use the unsubscribe link from the bottom of the email, or "
                "reply to it and you will be removed by hand.</p>"),
                "text/html; charset=utf-8")
        log_sub(email, "unsubscribe", "link")
        return self._send(200, page(
            "You're unsubscribed",
            "<p>No more emails will be sent to this address. Nothing else "
            "needed.</p>"), "text/html; charset=utf-8")

    def _subscribers(self):
        """The list itself, behind a token. Never public: these are real
        addresses belonging to other people, and /health already answers the
        only question that needs answering from outside.
        """
        want = os.environ.get("ADMIN_TOKEN", "")
        got = self.headers.get("X-Admin-Token", "")
        if not want:
            return self._send(503, {"error": "ADMIN_TOKEN is not configured"})
        if not hmac.compare_digest(want, got):
            return self._send(403, {"error": "forbidden"})
        live = sorted(r["email"] for r in subscriber_state().values()
                      if r["event"] == "subscribe")
        return self._send(200, {"count": len(live), "subscribers": live})

    def _subscribe(self, length, form):
        ip = self.client_address[0]
        if rate_limited(ip):
            msg = "too many signups from this connection, try later"
            return self._reply_sub(form, 429, {"error": msg},
                                   "Try again shortly", f"<p>{msg}.</p>")
        raw = self.rfile.read(length)
        try:
            if form:
                fields = parse_qs(raw.decode("utf-8", "replace"))
                email = clean_email((fields.get("email") or [""])[0])
                source = (fields.get("source") or [""])[0]
            else:
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                email = clean_email(body.get("email"))
                source = str(body.get("source", ""))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._reply_sub(form, 400, {"error": str(exc)},
                                   "Check that address", f"<p>{exc}.</p>")

        prior = subscriber_state().get(email)
        # A second signup is the normal case, not an error: people forget. Log
        # it so a resubscribe after an unsubscribe is recorded as consent.
        if not prior or prior["event"] != "subscribe":
            log_sub(email, "subscribe", source)
        return self._reply_sub(
            form, 200, {"ok": True, "email": email},
            "You're on the list",
            "<p>The week's numbers land in your inbox before Sunday's games. "
            "Every email has a one-click unsubscribe.</p>"
            "<p><a href='/week'>Back to this week</a></p>")

    def _reply_sub(self, form, code, payload, title, body):
        """A form POST navigates, so it needs a page; fetch() needs the JSON."""
        if form:
            return self._send(code, page(title, body),
                              "text/html; charset=utf-8")
        return self._send(code, payload)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/card", "/subscribe"):
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if length <= 0 or length > MAX_BODY:
            return self._send(400, {"error": "body must be 1 byte to 64 KiB"})
        if path == "/subscribe":
            ctype = (self.headers.get("Content-Type") or "").lower()
            form = "application/x-www-form-urlencoded" in ctype
            return self._subscribe(length, form)
        try:
            card = clean(json.loads(self.rfile.read(length)))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        late = too_late(card)
        if late:
            # Rejected whole rather than silently dropping the late games: a
            # card that quietly differs from what was sent is worse than one
            # that fails loudly.
            return self._send(409, {
                "error": "kickoff has passed for " + ", ".join(sorted(late)),
                "late": sorted(late),
            })

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
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
