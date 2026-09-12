"""SQLite storage for cross-venue NFL quote snapshots."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    ts          INTEGER NOT NULL,          -- unix seconds, UTC
    game_date   TEXT    NOT NULL,
    away        TEXT    NOT NULL,
    home        TEXT    NOT NULL,
    team        TEXT    NOT NULL,          -- the outcome being quoted
    venue       TEXT    NOT NULL,          -- 'kalshi' | 'poly'
    bid         REAL,
    bid_qty     REAL,
    ask         REAL,
    ask_qty     REAL
);
CREATE INDEX IF NOT EXISTS quotes_ts ON quotes (ts);
CREATE INDEX IF NOT EXISTS quotes_game ON quotes (game_date, away, home, team);

CREATE TABLE IF NOT EXISTS gaps (
    ts          INTEGER NOT NULL,
    game_date   TEXT    NOT NULL,
    away        TEXT    NOT NULL,
    home        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,          -- 'same_outcome' | 'two_sided'
    detail      TEXT    NOT NULL,          -- human-readable legs
    gross_cents REAL    NOT NULL,          -- edge before fees
    size        REAL    NOT NULL,          -- executable contracts at those prices
    net_dollars REAL    NOT NULL           -- profit after fees at that size
);
CREATE INDEX IF NOT EXISTS gaps_ts ON gaps (ts);

CREATE TABLE IF NOT EXISTS runs (
    ts          INTEGER NOT NULL,
    games       INTEGER NOT NULL,
    matched     INTEGER NOT NULL,
    gaps        INTEGER NOT NULL,
    seconds     REAL    NOT NULL,
    error       TEXT
);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_quotes(conn, rows):
    conn.executemany(
        "INSERT INTO quotes (ts, game_date, away, home, team, venue,"
        " bid, bid_qty, ask, ask_qty) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def insert_gaps(conn, rows):
    conn.executemany(
        "INSERT INTO gaps (ts, game_date, away, home, kind, detail,"
        " gross_cents, size, net_dollars) VALUES (?,?,?,?,?,?,?,?,?)", rows)


def insert_run(conn, row):
    conn.execute(
        "INSERT INTO runs (ts, games, matched, gaps, seconds, error)"
        " VALUES (?,?,?,?,?,?)", row)
