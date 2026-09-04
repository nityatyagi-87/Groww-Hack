from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from app.config import settings
from app.scoring import DEDUP_WINDOW_S

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  last_seen_ts REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  sensitivity TEXT NOT NULL DEFAULT 'med'
);

CREATE TABLE IF NOT EXISTS watchlist_items (
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  added_at REAL NOT NULL,
  PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT PRIMARY KEY,
  price REAL NOT NULL,
  prev_close REAL NOT NULL,
  day_open REAL NOT NULL,
  volume REAL NOT NULL,
  avg_volume REAL NOT NULL,
  atr_pct REAL NOT NULL DEFAULT 1.5,
  ts REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'demo'
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  event_type TEXT NOT NULL,
  score REAL NOT NULL,
  magnitude REAL NOT NULL,
  unusualness REAL NOT NULL,
  corroboration REAL NOT NULL,
  freshness REAL NOT NULL,
  payload TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_symbol_ts ON events(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS headlines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT,
  kind TEXT NOT NULL,
  sectors TEXT NOT NULL,
  symbols TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_headlines_ts ON headlines(ts);

CREATE TABLE IF NOT EXISTS seen_cursors (
  user_id TEXT PRIMARY KEY,
  pending_last_seen REAL NOT NULL,
  acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS event_reads (
  user_id TEXT NOT NULL,
  event_id INTEGER NOT NULL,
  read_at REAL NOT NULL,
  PRIMARY KEY (user_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_event_reads_user ON event_reads(user_id);
"""


async def get_db() -> aiosqlite.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.executescript(SCHEMA)
    await _migrate(db)
    await db.commit()
    return db


async def _migrate(db: aiosqlite.Connection) -> None:
    cur = await db.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in await cur.fetchall()}
    if "sensitivity" not in cols:
        await db.execute(
            "ALTER TABLE users ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'med'"
        )


async def ensure_user(db: aiosqlite.Connection, user_id: str) -> None:
    cur = await db.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if await cur.fetchone() is None:
        now = time.time()
        await db.execute(
            "INSERT INTO users(id, last_seen_ts, created_at, sensitivity) VALUES(?,?,?,?)",
            (user_id, 0, now, "med"),
        )
        await db.commit()


async def get_user_sensitivity(db: aiosqlite.Connection, user_id: str) -> str:
    cur = await db.execute("SELECT sensitivity FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    return (row["sensitivity"] if row else "med") or "med"


async def set_user_sensitivity(db: aiosqlite.Connection, user_id: str, level: str) -> str:
    level = level.lower()
    if level not in ("low", "med", "high"):
        level = "med"
    await ensure_user(db, user_id)
    await db.execute("UPDATE users SET sensitivity=? WHERE id=?", (level, user_id))
    await db.commit()
    return level


async def get_watchlist(db: aiosqlite.Connection, user_id: str) -> list[str]:
    cur = await db.execute(
        "SELECT symbol FROM watchlist_items WHERE user_id=? ORDER BY added_at",
        (user_id,),
    )
    rows = await cur.fetchall()
    return [r["symbol"] for r in rows]


async def all_watched_symbols(db: aiosqlite.Connection) -> list[str]:
    cur = await db.execute("SELECT DISTINCT symbol FROM watchlist_items")
    return [r["symbol"] for r in await cur.fetchall()]


async def symbol_watcher_counts(db: aiosqlite.Connection) -> dict[str, int]:
    """Param 5 — hot/cold tiering input: watchers per symbol."""
    cur = await db.execute(
        "SELECT symbol, COUNT(*) AS c FROM watchlist_items GROUP BY symbol"
    )
    return {r["symbol"]: int(r["c"]) for r in await cur.fetchall()}


async def upsert_quote(db: aiosqlite.Connection, q: dict[str, Any]) -> None:
    """Conflict policy: never overwrite a newer quote with an older one."""
    cur = await db.execute("SELECT ts FROM quotes WHERE symbol=?", (q["symbol"],))
    row = await cur.fetchone()
    if row and float(row["ts"]) > float(q["ts"]):
        return
    await db.execute(
        """INSERT INTO quotes(symbol,price,prev_close,day_open,volume,avg_volume,atr_pct,ts,source)
           VALUES(:symbol,:price,:prev_close,:day_open,:volume,:avg_volume,:atr_pct,:ts,:source)
           ON CONFLICT(symbol) DO UPDATE SET
             price=excluded.price, prev_close=excluded.prev_close, day_open=excluded.day_open,
             volume=excluded.volume, avg_volume=excluded.avg_volume, atr_pct=excluded.atr_pct,
             ts=excluded.ts, source=excluded.source""",
        q,
    )
    await db.commit()


async def insert_event(
    db: aiosqlite.Connection,
    *,
    symbol: str,
    event_type: str,
    score: float,
    magnitude: float,
    unusualness: float,
    corroboration: float,
    freshness: float,
    payload: dict,
    ts: Optional[float] = None,
) -> int:
    """
    Param 5 — de-dupe: same symbol+type within DEDUP_WINDOW_S collapses into one
    card with payload.count incremented (volatile symbols don't flood digest).
    """
    ts = ts or time.time()
    cur = await db.execute(
        """SELECT id, score, payload FROM events
           WHERE symbol=? AND event_type=? AND ts > ?
           ORDER BY ts DESC LIMIT 1""",
        (symbol, event_type, ts - DEDUP_WINDOW_S),
    )
    existing = await cur.fetchone()
    if existing:
        old_payload = json.loads(existing["payload"])
        count = int(old_payload.get("count") or 1) + 1
        old_payload.update(payload)
        old_payload["count"] = count
        new_score = max(float(existing["score"]), score)
        await db.execute(
            """UPDATE events SET score=?, magnitude=?, unusualness=?, corroboration=?,
               freshness=?, payload=?, ts=? WHERE id=?""",
            (
                new_score,
                magnitude,
                unusualness,
                corroboration,
                freshness,
                json.dumps(old_payload),
                ts,
                existing["id"],
            ),
        )
        await db.commit()
        return int(existing["id"])

    payload = {**payload, "count": payload.get("count", 1)}
    cur = await db.execute(
        """INSERT INTO events(symbol,event_type,score,magnitude,unusualness,corroboration,freshness,payload,ts)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            symbol,
            event_type,
            score,
            magnitude,
            unusualness,
            corroboration,
            freshness,
            json.dumps(payload),
            ts,
        ),
    )
    await db.commit()
    return cur.lastrowid or -1


async def unread_events_for_symbols(
    db: aiosqlite.Connection, user_id: str, symbols: list[str], limit: int
) -> list[dict]:
    """Param 3 — digest = unread events for watchlist, not timestamp cutoff."""
    if not symbols:
        return []
    placeholders = ",".join("?" * len(symbols))
    cur = await db.execute(
        f"""SELECT e.* FROM events e
            WHERE e.symbol IN ({placeholders})
              AND NOT EXISTS (
                SELECT 1 FROM event_reads r
                WHERE r.user_id=? AND r.event_id=e.id
              )
            ORDER BY e.score DESC, e.ts DESC
            LIMIT ?""",
        (*symbols, user_id, limit * 4),
    )
    rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


async def mark_events_read(
    db: aiosqlite.Connection, user_id: str, event_ids: list[int]
) -> int:
    """Param 3 — per-event ack."""
    now = time.time()
    n = 0
    for eid in event_ids:
        await db.execute(
            """INSERT OR IGNORE INTO event_reads(user_id, event_id, read_at)
               VALUES(?,?,?)""",
            (user_id, eid, now),
        )
        n += 1
    await db.commit()
    return n


async def recent_headline_for_symbol(
    db: aiosqlite.Connection, symbol: str, within_s: float = 7200.0
) -> Optional[dict]:
    cur = await db.execute(
        "SELECT title, kind, symbols, ts FROM headlines WHERE ts > ? ORDER BY ts DESC LIMIT 40",
        (time.time() - within_s,),
    )
    for r in await cur.fetchall():
        syms = json.loads(r["symbols"])
        if symbol in syms:
            return {"title": r["title"], "kind": r["kind"], "ts": r["ts"]}
    return None


async def boost_recent_price_event(
    db: aiosqlite.Connection,
    symbol: str,
    headline: str,
    boost: float,
    within_s: float = 300.0,
) -> Optional[int]:
    """
    Corroboration model: if a price event exists in-window, fold headline into it
    (×boost) instead of emitting a separate CATALYST.
    """
    cur = await db.execute(
        """SELECT id, score, payload FROM events
           WHERE symbol=? AND event_type IN ('MICRO_SPIKE','SESSION_MOVE','OPEN_GAP')
             AND ts > ?
           ORDER BY ts DESC LIMIT 1""",
        (symbol, time.time() - within_s),
    )
    row = await cur.fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    payload["has_headline"] = True
    payload["corroborated"] = True
    payload["corroboration_model"] = "price+volume+headline ×1.5"
    payload["headline"] = headline
    new_score = min(100.0, float(row["score"]) * boost)
    await db.execute(
        "UPDATE events SET score=?, payload=?, corroboration=? WHERE id=?",
        (new_score, json.dumps(payload), 90.0, row["id"]),
    )
    await db.commit()
    return int(row["id"])


async def insert_headline(db: aiosqlite.Connection, h: dict) -> int:
    cur = await db.execute(
        """INSERT INTO headlines(title,source,url,kind,sectors,symbols,ts)
           VALUES(?,?,?,?,?,?,?)""",
        (
            h["title"],
            h["source"],
            h.get("url"),
            h["kind"],
            json.dumps(h["sectors"]),
            json.dumps(h["symbols"]),
            h["ts"],
        ),
    )
    await db.commit()
    return cur.lastrowid or -1
