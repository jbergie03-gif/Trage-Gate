"""Trade Gate — a one-click-confirm risk gate and journal for Apex futures accounts.

It does NOT route orders. It decides whether you are allowed to trade, sizes the
trade from your stop, makes you confirm an exact order ticket, and logs it. You
place the order in your platform. Overrides are possible but recorded.

Run:  python3 app.py     then open http://127.0.0.1:8765
"""
from __future__ import annotations

import json
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import rules

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/paper")
def paper():
    """Live view of the paper engine. Simulated trades only, from paper_state.json."""
    return render_template("paper.html")


@app.get("/api/paper")
def api_paper():
    path = rules.BASE / "paper_state.json"
    if not path.exists():
        return jsonify({"running": False})
    with open(path) as f:
        state = json.load(f)
    state["running"] = True
    reports = sorted((rules.BASE / "reports").glob("session-*.md"), reverse=True)
    state["reports"] = [p.name for p in reports[:10]]
    return jsonify(state)


@app.get("/api/state")
def api_state():
    cfg = rules.load_config()
    with rules.db() as conn:
        return jsonify(rules.evaluate(cfg, conn))


@app.post("/api/settings")
def api_settings():
    data = request.get_json(force=True)
    cfg = rules.load_config()
    if data.get("account") in cfg["accounts"]:
        cfg["active_account"] = data["account"]
    if data.get("instrument") in cfg["instruments"]:
        cfg["instrument"] = data["instrument"]
    rules.save_config(cfg)
    with rules.db() as conn:
        return jsonify(rules.evaluate(cfg, conn))


@app.post("/api/size")
def api_size():
    d = request.get_json(force=True)
    cfg = rules.load_config()
    with rules.db() as conn:
        state = rules.evaluate(cfg, conn)
    try:
        sizing = rules.size_trade(
            cfg,
            d["side"],
            float(d["entry"]),
            float(d["stop"]),
            float(d["target"]),
            mae_cap=state["mae"]["ceiling"] if state["mae"]["enforced"] else None,
        )
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "errors": ["Entry, stop and target must all be numbers."]})
    sizing["blocks"] = state["blocks"]
    sizing["can_trade"] = state["can_trade"]
    return jsonify(sizing)


@app.post("/api/confirm")
def api_confirm():
    """Log a confirmed trade. Refuses when a rule blocks, unless override+reason."""
    d = request.get_json(force=True)
    cfg = rules.load_config()
    lim = rules.limits(cfg)
    with rules.db() as conn:
        state = rules.evaluate(cfg, conn)
        sizing = rules.size_trade(
            cfg,
            d["side"],
            float(d["entry"]),
            float(d["stop"]),
            float(d["target"]),
            mae_cap=state["mae"]["ceiling"] if state["mae"]["enforced"] else None,
        )
        if not sizing["ok"]:
            return jsonify({"ok": False, "errors": sizing["errors"]}), 400
        if not state["can_trade"]:
            reason = (d.get("override_reason") or "").strip()
            if not d.get("override") or len(reason) < 15:
                return jsonify({"ok": False, "errors": state["blocks"], "needs_override": True}), 403
            conn.execute(
                "INSERT INTO overrides (ts, trade_date, blocked_reason, justification) VALUES (?,?,?,?)",
                (
                    rules.now_ct().isoformat(),
                    rules.trade_date(),
                    " | ".join(state["blocks"]),
                    reason,
                ),
            )
        cur = conn.execute(
            "INSERT INTO trades (staged_at, trade_date, account, instrument, side, entry, stop, "
            "target, contracts, risk_dollars, reward_dollars, setup, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rules.now_ct().isoformat(),
                rules.trade_date(),
                lim.account,
                lim.instrument,
                d["side"].lower(),
                float(d["entry"]),
                float(d["stop"]),
                float(d["target"]),
                sizing["contracts"],
                sizing["risk_dollars"],
                sizing["reward_dollars"],
                (d.get("setup") or "").strip()[:120],
                (d.get("notes") or "").strip()[:500],
            ),
        )
        conn.commit()
        state = rules.evaluate(cfg, conn)
    return jsonify({"ok": True, "trade_id": cur.lastrowid, "state": state})


@app.post("/api/close")
def api_close():
    """Record the exit of the open trade.

    P&L is net of commissions, because Apex judges a qualifying day on net profit —
    a gross $300 day on a 100K is not a qualifying day once fees come out.
    """
    d = request.get_json(force=True)
    cfg = rules.load_config()
    lim = rules.limits(cfg)
    with rules.db() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=?", (int(d["trade_id"]),)).fetchone()
        if row is None:
            return jsonify({"ok": False, "errors": ["No such trade."]}), 404
        if row["pnl"] is not None:
            return jsonify({"ok": False, "errors": ["Trade already closed."]}), 400
        exit_price = float(d["exit_price"])
        points = (
            exit_price - row["entry"] if row["side"] == "long" else row["entry"] - exit_price
        )
        inst = cfg["instruments"].get(row["instrument"], cfg["instruments"][lim.instrument])
        gross = points * row["contracts"] * float(inst["point_value"])
        fees = row["contracts"] * float(inst["commission_round_trip"])
        pnl = round(gross - fees, 2)
        conn.execute(
            "UPDATE trades SET exit_price=?, pnl=?, closed_at=?, notes=COALESCE(?, notes) WHERE id=?",
            (
                exit_price,
                pnl,
                rules.now_ct().isoformat(),
                (d.get("notes") or None),
                row["id"],
            ),
        )
        conn.commit()
        state = rules.evaluate(cfg, conn)
    return jsonify(
        {"ok": True, "pnl": pnl, "gross": round(gross, 2), "fees": round(fees, 2), "state": state}
    )


@app.post("/api/payout")
def api_payout():
    """Record a payout request. Resets the consistency cycle once approved."""
    d = request.get_json(force=True)
    cfg = rules.load_config()
    with rules.db() as conn:
        lim = rules.limits(cfg, payouts_taken=rules.payouts_taken(conn, cfg["active_account"]))
        conn.execute(
            "INSERT INTO payouts (account, requested_on, amount, approved) VALUES (?,?,?,?)",
            (
                lim.account,
                rules.trade_date(),
                float(d["amount"]),
                1 if d.get("approved") else 0,
            ),
        )
        conn.commit()
        return jsonify({"ok": True, "state": rules.evaluate(cfg, conn)})


@app.get("/api/journal")
def api_journal():
    cfg = rules.load_config()
    lim = rules.limits(cfg)
    with rules.db() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE account=? ORDER BY id DESC LIMIT 200", (lim.account,)
        ).fetchall()
        ovr = conn.execute(
            "SELECT * FROM overrides ORDER BY id DESC LIMIT 50"
        ).fetchall()
        stats = rules.account_totals(
            conn,
            lim.account,
            lim.min_daily_profit,
            since=rules.last_payout_date(conn, lim.account),
        )
    trades = [dict(r) for r in rows]
    closed = [t for t in trades if t["pnl"] is not None]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] < 0]
    by_setup: dict[str, dict] = {}
    for t in closed:
        k = t["setup"] or "(untagged)"
        s = by_setup.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0})
        s["n"] += 1
        s["pnl"] = round(s["pnl"] + t["pnl"], 2)
        s["wins"] += 1 if t["pnl"] > 0 else 0
    return jsonify(
        {
            "trades": trades,
            "overrides": [dict(r) for r in ovr],
            "stats": {
                **stats,
                "closed": len(closed),
                "win_rate": round(len(wins) / len(closed), 4) if closed else 0,
                "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
                "by_setup": by_setup,
            },
        }
    )


if __name__ == "__main__":
    import os

    port = int(os.environ.get("TRADE_GATE_PORT", 8765))
    print(f"Trade Gate on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
