import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("LEADLENS_DB", str(Path(__file__).resolve().parent.parent / "data" / "leadlens.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL, name_norm TEXT, domain TEXT, website TEXT, industry TEXT,
  city TEXT, state TEXT, employees INTEGER, revenue REAL, phone TEXT, email TEXT,
  owner_name TEXT, year_founded INTEGER, rating REAL, review_count INTEGER, description TEXT,
  score REAL DEFAULT 0, tier TEXT DEFAULT 'D', confidence REAL DEFAULT 0,
  breakdown TEXT DEFAULT '{}', flags TEXT DEFAULT '[]',
  status TEXT DEFAULT 'new', enrichment TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_tier ON leads(tier);
CREATE INDEX IF NOT EXISTS idx_leads_state ON leads(state);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_name ON leads(name_norm, state);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))
