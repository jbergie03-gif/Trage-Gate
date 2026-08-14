"""Drives the live HTTP API the way the dashboard does, to prove the endpoints agree
with the rule engine: size -> confirm -> close -> lockout -> override -> payout.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("TRADE_GATE_TEST_PORT", 8766))
BASE = f"http://127.0.0.1:{PORT}"
CONFIG = HERE / "config.json"
fails = []

# The test drives a server of its own on a throwaway journal, so a real trading record is
# never written to, read from, or depended on by the assertions below.
_db = Path(tempfile.mkdtemp(prefix="tradegate-test-")) / "journal.db"
_env = {**os.environ, "TRADE_GATE_DB": str(_db), "TRADE_GATE_PORT": str(PORT)}
_server = subprocess.Popen([sys.executable, str(HERE / "app.py")], env=_env, cwd=HERE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
atexit.register(_server.terminate)

# The gate refuses trades outside the session window, so widen it for the test run
# and always put the real config back.
shutil.copy(CONFIG, str(CONFIG) + ".bak")
atexit.register(lambda: shutil.move(str(CONFIG) + ".bak", CONFIG))
_cfg = json.loads(CONFIG.read_text())
_cfg["my_rules"]["session_start_ct"] = "00:00"
_cfg["my_rules"]["session_end_ct"] = "23:59"
_cfg["my_rules"]["cooldown_minutes_after_loss"] = 0
CONFIG.write_text(json.dumps(_cfg, indent=2))

for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/state", timeout=1).read()
        break
    except Exception:
        time.sleep(0.5)
else:
    sys.exit(f"test server never came up on {BASE}")


def call(path, body=None):
    if body is None:
        req = urllib.request.Request(BASE + path)
    else:
        req = urllib.request.Request(
            BASE + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


print("--- /api/state ---")
code, s = call("/api/state")
check("200", code == 200)
check("account is 100K MES", s["limits"]["account"] == "100K" and s["limits"]["instrument"] == "MES")
check("no trades yet", s["day"]["trades"] == 0)
check("payout locked with reasons", not s["payout"]["eligible"] and s["payout"]["missing"])
print("     missing:", s["payout"]["missing"])

print("\n--- /api/settings switches account and instrument ---")
code, s = call("/api/settings", {"account": "50K", "instrument": "ES"})
check("50K ES applied", s["limits"]["account"] == "50K" and s["limits"]["instrument"] == "ES")
check("50K risk is $100", s["limits"]["risk_per_trade"] == 100.0)
check("ES max 6 contracts", s["limits"]["max_contracts"] == 6)
code, s = call("/api/settings", {"account": "100K", "instrument": "MES"})
check("back to 100K MES", s["limits"]["account"] == "100K")
code, s = call("/api/settings", {"account": "999K"})
check("garbage account ignored", s["limits"]["account"] == "100K")

print("\n--- /api/size ---")
code, z = call("/api/size", {"side": "long", "entry": 5000, "stop": 4994, "target": 5015})
check("sizes 5 MES", z["contracts"] == 5, str(z["contracts"]))
check("nets out fees", z["commission"] == 6.2 and z["net_if_target_hit"] == 368.8,
      f"{z['reward_dollars']} gross -> {z['net_if_target_hit']} net")
check("flags a qualifying day", z["makes_qualifying_day"])
code, z = call("/api/size", {"side": "long", "entry": 5000, "stop": 4994, "target": 5006})
check("rejects 1:1", not z["ok"])
code, z = call("/api/size", {"side": "long", "entry": "abc", "stop": 4994, "target": 5006})
check("rejects non-numeric input", not z["ok"], str(z["errors"]))

print("\n--- /api/confirm + /api/close: a winning day ---")
code, j = call(
    "/api/confirm",
    {"side": "long", "entry": 5000, "stop": 4994, "target": 5015, "setup": "orb reclaim"},
)
check("logged", code == 200 and j["ok"], str(j)[:200])
tid = j.get("trade_id")
check("gate now blocks a second trade while open",
      any("still open" in b for b in j["state"]["blocks"]))

code, j = call("/api/close", {"trade_id": tid, "exit_price": 5015, "notes": "target hit"})
check("close computes P&L net of fees",
      j["ok"] and j["gross"] == 375.0 and j["fees"] == 6.2 and j["pnl"] == 368.8, str(j.get("pnl")))
st = j["state"]
check("day locked after target", not st["can_trade"])
check("target-hit message", any("TARGET HIT" in b for b in st["blocks"]), str(st["blocks"]))
check("day counts as qualifying", st["day"]["qualifies"])
check("qualifying days = 1", st["payout"]["qualifying_days"] == 1)

print("\n--- override requires a real reason and is recorded ---")
body = {"side": "long", "entry": 5000, "stop": 4994, "target": 5015}
code, j = call("/api/confirm", body)
check("blocked without override", code == 403 and j.get("needs_override"))
code, j = call("/api/confirm", {**body, "override": True, "override_reason": "just one more"})
check("short reason rejected", code == 403, str(code))
code, j = call(
    "/api/confirm",
    {**body, "override": True, "override_reason": "I know this breaks the rule and I am doing it anyway"},
)
check("override accepted with a full reason", code == 200 and j["ok"])
code, jr = call("/api/journal")
check("override is on the record", len(jr["overrides"]) == 1, str(jr["overrides"]))
print("     recorded:", jr["overrides"][0]["justification"])

# Clean up the overridden trade so the journal stays truthful about the test.
code, j = call("/api/close", {"trade_id": j["trade_id"], "exit_price": 4994})
check("overridden trade closed at a loss", j["pnl"] == -156.2, str(j.get("pnl")))
check("day back under target, so the gate reopens for the last trade",
      j["state"]["can_trade"] and j["state"]["day"]["trades"] == 2, str(j["state"]["blocks"]))
check("one trade left before the daily cap",
      j["state"]["day"]["trades"] == j["state"]["rules"]["max_trades_per_day"] - 1)

print("\n--- /api/journal statistics ---")
code, jr = call("/api/journal")
s = jr["stats"]
check("2 closed trades", s["closed"] == 2, str(s["closed"]))
check("win rate 50%", s["win_rate"] == 0.5)
check("avg win 368.80", s["avg_win"] == 368.8, str(s["avg_win"]))
check("avg loss -156.20", s["avg_loss"] == -156.2, str(s["avg_loss"]))
check("setups tracked", "orb reclaim" in s["by_setup"], str(list(s["by_setup"])))

print("\n--- /api/payout ---")
code, j = call("/api/payout", {"amount": 500, "approved": True})
check("payout logged", j["ok"])
check("payouts taken = 1", j["state"]["limits"]["payouts_taken"] == 1)
check("next cap steps to 2500", j["state"]["limits"]["next_payout_cap"] == 2500.0)
check("consistency cycle reset", j["state"]["account"]["cycle_days"] == 0,
      str(j["state"]["account"]["cycle_days"]))

print("\n--- dashboard HTML renders ---")
with urllib.request.urlopen(urllib.request.Request(BASE + "/")) as r:
    html = r.read().decode()
check("200", r.status == 200)
for token in ["payoutBox", "kWith", "targetNote", "logPayout", "net_if_target_hit"]:
    check(f"template references {token}", token in html)
check("no stale schema references",
      "L.unverified" not in html and "S.rules.consistency_pct" not in html
      and "days_at_plan_pace" not in html)

print("\n" + ("ALL API CHECKS PASSED" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
