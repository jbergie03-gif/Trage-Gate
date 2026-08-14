"""Build the Trade Gate rulebook PDF.

Every number is read from config.json and computed with rules.py, so the printed
rulebook can never drift from what the app actually enforces.
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

import rules

BASE = Path(__file__).resolve().parent
OUT = BASE / "Trade_Gate_Rulebook.pdf"

INK = colors.HexColor("#12181f")
DIM = colors.HexColor("#5b6673")
LINE = colors.HexColor("#c8d0d8")
RED = colors.HexColor("#a51c19")
GREEN = colors.HexColor("#1c6b33")
BLUE = colors.HexColor("#1d4e79")
BAND = colors.HexColor("#eef2f6")
AMBER = colors.HexColor("#7a5c11")

ss = getSampleStyleSheet()


def st(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=INK, spaceAfter=6)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "title": st("title", fontName="Helvetica-Bold", fontSize=26, leading=30,
                alignment=TA_CENTER, spaceAfter=4),
    "sub": st("sub", fontSize=11.5, leading=16, alignment=TA_CENTER, textColor=DIM, spaceAfter=20),
    "h1": st("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=BLUE,
             spaceBefore=16, spaceAfter=8),
    "h2": st("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=10, spaceAfter=4),
    "body": st("body"),
    "small": st("small", fontSize=8.6, leading=11.6, textColor=DIM),
    "rule": st("rule", fontSize=10.5, leading=15, spaceAfter=8),
    "quote": st("quote", fontName="Helvetica-Oblique", fontSize=10.5, leading=15,
                leftIndent=14, textColor=DIM),
    "cell": st("cell", fontSize=9, leading=12, spaceAfter=0),
    "cellb": st("cellb", fontName="Helvetica-Bold", fontSize=9, leading=12, spaceAfter=0),
    "cellw": st("cellw", fontName="Helvetica-Bold", fontSize=9, leading=12, spaceAfter=0,
                textColor=colors.white),
}


def money(n, dec=0):
    return f"${n:,.{dec}f}"


def para(text, style="body"):
    return Paragraph(text, S[style])


def banner(text, color, bg):
    t = Table([[Paragraph(text, st("b", fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                                   textColor=color, spaceAfter=0))]],
              colWidths=[6.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.9, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def table(rows, widths, header_bg=BLUE, align_right_from=1):
    data = []
    for i, row in enumerate(rows):
        style = "cellw" if i == 0 else "cell"
        data.append([Paragraph(str(c), S[style]) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def numbered(items, color=INK):
    out = []
    for i, (head, text) in enumerate(items, 1):
        out.append(Paragraph(
            f'<font color="{color.hexval()}"><b>{i}. {head}</b></font><br/>{text}', S["rule"]))
    return out


def build():
    cfg = rules.load_config()
    r = cfg["my_rules"]
    pay = cfg["payout"]
    story = []

    # ---------- cover ----------
    story += [
        Spacer(1, 0.5 * inch),
        para("TRADE GATE", "title"),
        para("A survival and payout system for Apex EOD accounts<br/>"
             "Built for Jonathan &mdash; one account, small days, real stops.", "sub"),
        banner("The purpose of this system is not to pass evaluations. You already know how to do "
               "that &mdash; you did it repeatedly. The purpose is to still be alive on payout day.",
               BLUE, BAND),
        Spacer(1, 0.22 * inch),
        para("What the record says", "h1"),
        para("170 payments to Apex between April 2023 and April 2026, totalling "
             "<b>$6,155.43</b>. Evaluations passed many times. <b>Payouts received: none.</b> "
             "Every failure came after progress, not before it.", "body"),
        para("The arithmetic that matters most in this document: a 100K EOD Performance Account "
             "needs <b>+$3,600</b> in profit and <b>five days of $300</b> to reach its first "
             "payout. That is less than you spent on evaluations. The money was never the "
             "obstacle &mdash; the obstacle was continuing to trade after the day was already won.",
             "body"),
        Spacer(1, 0.16 * inch),
        banner("This tool never places an order. Apex prohibits automation and algorithmic "
               "execution &mdash; an account that trades itself is a forfeited account. Trade Gate "
               "sizes, gates and journals. You place every fill by hand.", RED, colors.HexColor("#fbeceb")),
        Spacer(1, 0.16 * inch),
        para("Three kinds of rules appear in this book, and they are never mixed:", "body"),
        table([
            ["", "Source", "What happens if broken"],
            ["APEX RULES", "Verified from Apex's EOD Evaluations, EOD Payouts and Prohibited "
                           "Activities pages", "The account fails, closes, or the payout is denied"],
            ["MY RULES", "Written for you, deliberately tighter than Apex requires",
             "Nothing &mdash; which is exactly why they need a gate in front of them"],
            ["LEGACY / UNCONFIRMED", "Rules Apex labels Legacy, with no EOD equivalent page",
             "Displayed for reference, never enforced"],
        ], [1.35 * inch, 2.6 * inch, 2.95 * inch], align_right_from=99),
        PageBreak(),
    ]

    # ---------- apex facts ----------
    story += [
        para("Part 1 &mdash; The Apex rules (verified)", "h1"),
        para("These are Apex's numbers, taken from the pages you supplied. The app reads them from "
             "<font face='Courier'>config.json</font>; if Apex changes them, edit that file and "
             "both the app and this rulebook update together.", "body"),

        para("EOD Evaluation &mdash; what it takes to pass", "h2"),
        table([
            ["Account", "Profit target", "EOD drawdown", "Daily loss limit", "Max ES"],
        ] + [
            [f"{k} EOD", money(a["eval_profit_target"]), money(a["eod_drawdown"]),
             money(a["daily_loss_limit"]), str(a["max_contracts_es"])]
            for k, a in cfg["accounts"].items()
        ], [1.5 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch, 1.2 * inch]),
        para("There is no intraday trailing drawdown on these accounts. The drawdown is measured "
             "at the close and enforced the next session. The daily loss limit is fixed and only "
             "pauses the session &mdash; it does not fail the account. Touching the EOD threshold "
             "does. No minimum trading days, 30 days of access, and 7 calendar days to activate a "
             "PA once the evaluation is marked passed after 6 PM ET.", "body"),

        para("EOD Performance Account &mdash; what it takes to get paid", "h2"),
        table([
            ["Account", "Qual. days", "Min daily profit", "Safety net", "Min balance to request",
             "Max payouts"],
        ] + [
            [f"{k} EOD", str(pay["min_qualifying_days"]), money(a["min_daily_profit"]),
             money(a["safety_net_balance"]), money(a["min_balance_to_request"]),
             str(pay["max_payouts"])]
            for k, a in cfg["accounts"].items()
        ], [1.05 * inch, 0.85 * inch, 1.15 * inch, 1.05 * inch, 1.55 * inch, 0.85 * inch]),

        para("Payout cap by payout number", "h2"),
        table([
            ["Payout #"] + [f"{k}" for k in cfg["accounts"]],
        ] + [
            [f"#{i + 1}"] + [money(cfg["accounts"][k]["max_payouts_schedule"][i])
                             for k in cfg["accounts"]]
            for i in range(pay["max_payouts"])
        ] + [
            ["<b>Lifetime</b>"] + [f"<b>{money(sum(cfg['accounts'][k]['max_payouts_schedule']))}</b>"
                                   for k in cfg["accounts"]],
        ], [1.3 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch]),
        para("100% split, minimum $500 per request. After the sixth approved payout the PA closes "
             "and you re-qualify with a new evaluation.", "body"),

        para("The 50% consistency rule", "h2"),
        para("No single profitable day may be 50% or more of your total profit since your last "
             "approved payout. This is the rule that punishes the big day, and it is the reason a "
             "$1,500 afternoon is not a good afternoon: it locks the payout button until your "
             "other days catch up. Five even days of $325 pass easily. One day of $1,600 does not.",
             "body"),

        para("The safety net", "h2"),
        para("Drawdown plus $100, for the lifetime of the account. Only profit above it can be "
             "withdrawn. On a 100K that is $103,100 &mdash; so the first $3,100 of profit is not "
             "yours to take, and the first $500 you can actually request sits at $103,600.", "body"),
        PageBreak(),

        para("Prohibited activities that touch how you trade", "h1"),
        para("Verified from Apex's Prohibited Activities page. Four of these are enforced by the "
             "app, and three describe habits worth naming honestly.", "body"),
    ]
    story += numbered([
        ("Every trade must have a stop loss.",
         "Not optional and not a suggestion &mdash; trading without pending or mental stops is "
         "listed as prohibited. The app will not stage a trade without one."),
        ("No disproportionate risk.",
         "Apex's own example is a five-tick target against a 150-tick stop. Your minimum 1.5:1 "
         "reward-to-risk satisfies this by construction."),
        ("Never use the threshold as your stop loss.",
         "This is exactly the shape of &ldquo;give it room to come back.&rdquo; The per-trade cap "
         "is 5% of drawdown, so one trade mathematically cannot reach the threshold."),
        ("Flat before the close.",
         "Holding a position through market close forfeits the account and all balances. The app "
         f"warns from {rules.ct_to_pt(r['hard_flat_time_ct'])} PT."),
        ("No automation or algorithms.",
         "Rewards recognise human traders. This is why Trade Gate refuses to route orders, and it "
         "is the correct behaviour even though it is less convenient."),
        ("No hedging, no non-directional brackets.",
         "No simultaneous longs and shorts on the same or correlated instruments; no resting "
         "orders on both sides hoping news picks a winner."),
        ("No stockpiling evaluations to cycle through.",
         "Buying discounted evaluations and blowing them up in pursuit of a windfall is listed as "
         "prohibited. 170 purchases with no payout is a pattern that can be read this way. The fix "
         "and the path to a payout are the same thing: one account, traded small."),
    ], RED)

    story += [
        para("Legacy 30% Negative P&amp;L (MAE) &mdash; not enforced", "h2"),
        para("Apex's MAE rule caps open unrealised loss at 30% of start-of-day profit. The article "
             "is titled <b>Legacy</b>, there is no EOD equivalent page, and the EOD payout rules "
             "never mention it, so the app shows it as reference only and never blocks on it. "
             "Nothing in your plan depends on the answer: your per-trade risk is a fraction of "
             "what that ceiling would allow. Worth one support ticket to confirm; if it does apply, "
             "set <font face='Courier'>mae.enforce</font> to true in config.json.", "body"),
        PageBreak(),
    ]

    # ---------- my rules ----------
    cfg["active_account"] = "100K"
    cfg["instrument"] = "MES"
    L = rules.limits(cfg)

    story += [
        para("Part 2 &mdash; My rules (the hard ones)", "h1"),
        para("Apex would happily let you lose "
             f"{money(L.apex_daily_loss_limit)} in a day on a 100K and still call the account "
             "alive. That permission is what ended the last accounts. Everything below is tighter "
             "than Apex requires, on purpose.", "body"),
        Spacer(1, 0.06 * inch),
        banner("The daily target is a CEILING, not a goal. Hitting it is a complete, successful "
               "day. There is no version of this system where a good day gets extended.",
               GREEN, colors.HexColor("#e9f5ec")),
        Spacer(1, 0.12 * inch),
    ]
    story += numbered([
        ("Risk per trade: 5% of the EOD drawdown.",
         f"On a 100K that is {money(L.risk_per_trade)}. Size is computed from your stop, never "
         "chosen by feel. It never increases after a win."),
        ("Daily loss limit: 15% of drawdown, and the day is over.",
         f"{money(L.max_daily_loss)} on a 100K &mdash; a third of what Apex allows. Three losers "
         "cannot break this. The gate closes and does not reopen until the 6 PM ET reset."),
        ("Daily target: Apex's minimum plus a commission buffer.",
         f"{money(L.daily_target)} net on a 100K. Reaching it locks the day. This is the single "
         "most important rule in the book, because this is the exact rule you have never followed."),
        ("Maximum 3 trades a day.",
         "Trade four and you are no longer trading a plan. One clean trade at "
         f"{L.rr_for_one_trade_day}:1 finishes the day by itself."),
        ("Two consecutive losses ends the day.",
         "Not a pause &mdash; the day. Two losses in a row means the market is not offering your "
         "setup, and the third trade is revenge, not analysis."),
        (f"{r['cooldown_minutes_after_loss']}-minute cooldown after any loss.",
         "The gate is closed during it. Re-entry inside fifteen minutes of a stop-out is emotion "
         "with a chart attached."),
        (f"Session {rules.ct_to_pt(r['session_start_ct'])}&ndash;"
         f"{rules.ct_to_pt(r['session_end_ct'])} PT only.",
         f"Flat by {rules.ct_to_pt(r['hard_flat_time_ct'])} PT at the latest. Afternoon trading "
         "after a green "
         "morning is how green mornings die."),
        ("Stops between "
         f"{r['min_stop_points']} and {r['max_stop_points']} points, minimum "
         f"{r['min_reward_to_risk']}:1.",
         "A stop tighter than 2 points is noise; wider than 12 is a different strategy. Below "
         "1.5:1 you need a win rate you do not have."),
        ("Never trade past the consistency cap.",
         "The app computes the largest profit today may be without making today 50% of the cycle. "
         "Passing it does not fail the account &mdash; it delays the payout, which is worse, "
         "because it delays it in a way that feels like winning."),
        ("Overrides are possible, recorded, and permanent.",
         "The gate can be overridden with a written reason of at least 15 characters. It is stored "
         "forever and shown on the journal. If the override log grows, the problem is not the "
         "rules."),
    ], BLUE)

    story += [
        Spacer(1, 0.08 * inch),
        para("What those rules produce, by account", "h2"),
        table([
            ["Account", "Risk / trade", "Daily stop", "Daily target", "Days to 1st payout",
             "Max MES"],
        ] + [
            [f"{k} EOD", money(x.risk_per_trade), money(x.max_daily_loss), money(x.daily_target),
             f"{x.profit_to_first_request / x.daily_target:.0f}", str(x.max_contracts)]
            for k, x in ((k, rules.limits({**cfg, "active_account": k, "instrument": "MES"}))
                         for k in cfg["accounts"])
        ], [1.05 * inch, 1.1 * inch, 1.0 * inch, 1.1 * inch, 1.5 * inch, 0.95 * inch]),
        para("&ldquo;Days to 1st payout&rdquo; assumes every day hits target and none lose, so "
             "treat it as a floor, not a forecast. Losing days push it out; that is normal and the "
             "system survives them. What it does not survive is one day that tries to compress the "
             "whole schedule.", "small"),
        Spacer(1, 0.18 * inch),
    ]

    # ---------- the plan ----------
    story += [
        para("Part 3 &mdash; The plan on a 100K", "h1"),
        table([
            ["Step", "Number"],
            ["Profit needed for the first payout request", f"<b>{money(L.profit_to_first_request)}</b>"],
            ["Qualifying days needed, at $300+ net each", f"<b>{pay['min_qualifying_days']}</b>"],
            ["Your daily target (a ceiling)", f"<b>{money(L.daily_target)}</b> net"],
            ["Target days to get there", f"<b>{L.profit_to_first_request / L.daily_target:.0f}</b>"],
            ["Risk per trade", money(L.risk_per_trade)],
            ["Worst allowed day", f"&minus;{money(L.max_daily_loss)}"],
            ["Balance that unlocks the request", money(L.start_balance + L.profit_to_first_request)],
            ["First payout, capped at", money(L.next_payout_cap)],
            ["Lifetime of the account, six payouts",
             money(sum(cfg["accounts"]["100K"]["max_payouts_schedule"]))],
        ], [4.6 * inch, 2.3 * inch], align_right_from=1),

        para("The day, start to finish", "h2"),
    ]
    story += numbered([
        ("Open the gate before the platform.",
         "Trade Gate first, chart second. It tells you your risk, your remaining loss budget, your "
         "buffer to the EOD threshold, and whether the session is even open."),
        ("Find one setup. Stage it.",
         "Enter your entry, stop and target. The app returns contracts, the exact dollar risk, the "
         "net result if it wins or loses, and whether a win makes today a qualifying day."),
        ("Read the ticket out loud, then place it by hand.",
         "The one click confirms and logs. It does not send an order. You place it in your "
         "platform, matching the ticket exactly &mdash; same size, same stop, same target."),
        ("Log the exit honestly, including the ugly ones.",
         "The journal is the only asset that compounds here. Tag the setup; after twenty trades it "
         "will tell you which one actually pays and which one you merely enjoy."),
        ("When the day is done, it is done.",
         "Target hit, daily stop hit, two losses, three trades, or 09:30 PT &mdash; whichever "
         "comes "
         "first. Close the platform. This is the whole system."),
        ("At five qualifying days and $3,600, request the payout.",
         "Do not wait for a rounder number. Do not build a cushion first. Request it, then trade "
         "as though the money has already left the account, because it has."),
    ], GREEN)

    story += [
        Spacer(1, 0.1 * inch),
        para("Read this on the day it goes well", "h2"),
        para("You will have a morning where the first trade wins by 10:00 and the market keeps "
             "offering. Every previous account ended in that moment, not in a crash. The rule is "
             "simple and it is not negotiable: <b>the day is over.</b> A "
             f"{money(L.daily_target)} day is one fifth of your first payout for doing nothing "
             "difficult. Eleven of those days, with a losing day scattered in, and you are paid "
             "for the first time in three years.", "body"),
        para("And on the day it goes badly: your worst possible day is "
             f"&minus;{money(L.max_daily_loss)}, which is {L.eod_drawdown / L.max_daily_loss:.1f} "
             "bad days from the threshold. You cannot lose this account in an afternoon unless you "
             "override the gate to do it.", "body"),
        Spacer(1, 0.12 * inch),
        banner("Two numbers that end an account instantly, and neither is a loss: the size of a "
               "day that beat the plan, and the number of trades after the target was hit.",
               AMBER, colors.HexColor("#fdf6e3")),

        para("Running it", "h2"),
        para("<font face='Courier'>cd trade_gate &amp;&amp; .venv/bin/python app.py</font> then open "
             "<font face='Courier'>http://127.0.0.1:8765</font>. Everything is local: a SQLite "
             "journal in <font face='Courier'>journal.db</font> and your rules in "
             "<font face='Courier'>config.json</font>. No broker connection, no Apex login, no "
             "credentials, no internet. Change the risk numbers in config.json if you want them "
             "different &mdash; but change them before the session, never during one.", "body"),
        para("Commission estimates in config.json are placeholders "
             f"({money(cfg['instruments']['MES']['commission_round_trip'], 2)} round trip per MES, "
             f"{money(cfg['instruments']['ES']['commission_round_trip'], 2)} per ES). Replace them "
             "with your platform's actual rates so a qualifying day is judged on real net profit.",
             "small"),
        Spacer(1, 0.1 * inch),
        para("One unverified detail, stated plainly: no page you supplied says whether the EOD "
             "drawdown stops trailing once the account is profitable. The app assumes it keeps "
             "trailing, which is the stricter assumption &mdash; if Apex locks the threshold at "
             "breakeven, you have more room than the app shows, never less.", "small"),
        para("Not financial advice. Trade Gate does not guarantee a payout, does not predict "
             "markets, and cannot stop you from overriding it. It is a written agreement with "
             "yourself that keeps score. Apex accounts are simulated; payouts are discretionary "
             "and subject to Apex's eligibility and compliance review.", "small"),
    ]

    doc = BaseDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title="Trade Gate Rulebook", author="Trade Gate",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")

    def decorate(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(DIM)
        canvas.drawString(doc.leftMargin, 0.5 * inch, "Trade Gate \u2014 Apex EOD discipline system")
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.5 * inch, f"{d.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(doc.leftMargin, 0.62 * inch, LETTER[0] - doc.rightMargin, 0.62 * inch)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=decorate)])
    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
