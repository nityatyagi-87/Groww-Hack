from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.alt_data import SYMBOL_EXPOSURE, factor_snapshot, overlay_series, us_index_sparks
from app.bus import bus
from app.chart import TF_SPEC, build_ohlc
from app.config import settings
from app.db import all_watched_symbols, ensure_user, get_db, get_watchlist
from app.routes.digest import uid
from app.scoring import CONFLICT_TOLERANCE, MICRO_Z_THRESHOLD, EventType
from app.seed import BASE_QUOTES, DEFAULT_WATCHLIST

router = APIRouter(prefix="/api", tags=["chart"])


@router.get("/chart/{symbol}")
async def chart(
    symbol: str,
    tf: str = Query("1D", pattern="^(1D|1W|1M|3M|1Y)$"),
):
    sym = symbol.upper()
    if sym not in BASE_QUOTES:
        raise HTTPException(404, "Unknown symbol")
    live = bus.latest.get(sym, {}).get("price")
    if live is None:
        db = await get_db()
        cur = await db.execute("SELECT price FROM quotes WHERE symbol=?", (sym,))
        row = await cur.fetchone()
        await db.close()
        live = row["price"] if row else BASE_QUOTES[sym]["price"]
    try:
        data = build_ohlc(sym, tf, live_price=float(live))  # type: ignore[arg-type]
    except KeyError:
        raise HTTPException(404, "Unknown symbol")
    data["timeframes"] = list(TF_SPEC.keys())
    data["overlays"] = overlay_series(sym, n=min(40, len(data["candles"])))
    data["exposure"] = SYMBOL_EXPOSURE.get(sym)
    return data


@router.get("/alt/factors")
async def alt_factors():
    """Single weather/crop overlay factor set (Param 6)."""
    return factor_snapshot()


@router.get("/alt/us-indexes")
async def alt_us_indexes():
    return {"indexes": us_index_sparks(), "note": "US overnight — DELAYED vs India session"}


@router.get("/symbol/{symbol}/events")
async def symbol_events(symbol: str, limit: int = 8):
    sym = symbol.upper()
    db = await get_db()
    cur = await db.execute(
        "SELECT id, event_type, score, payload, ts FROM events WHERE symbol=? ORDER BY ts DESC LIMIT ?",
        (sym, limit),
    )
    rows = []
    for r in await cur.fetchall():
        rows.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "score": r["score"],
                "payload": json.loads(r["payload"]),
                "ts": r["ts"],
            }
        )
    await db.close()
    return {"symbol": sym, "items": rows}


@router.get("/policy")
async def product_policy():
    db = await get_db()
    union = await all_watched_symbols(db)
    await db.close()
    return {
        "meaningful_change": {
            "taxonomy": [t.value for t in EventType],
            "significance": f"|z|×vol_confirm×time_decay; emit |z|≥{MICRO_Z_THRESHOLD}",
            "sensitivity": "low/med/high multiplies digest threshold floor",
            "corroboration_model": "price+volume+headline → one card ×1.5",
            "rank": "score × time_decay(away window)",
        },
        "surface": [
            "Digest card: symbol · type · magnitude · reason · ts · freshness · peer",
            "Peer flag: IDIOSYNCRATIC vs SECTOR (vs sector median)",
            "US indexes → SymbolDetail",
            "One alt overlay: weather/crop",
            "LIVE / DELAYED / STALE / CONFLICT badges",
        ],
        "persistence": {
            "event_reads": "Per-user per-event ack; digest = unread watchlist events",
        },
        "data_quality": {
            "LIVE": f"≤{settings.live_max_age_s}s",
            "DELAYED": f"≤{settings.delayed_max_age_s}s — score ×0.5 before threshold",
            "STALE": f">{settings.delayed_max_age_s}s",
            "CONFLICT": f"sources disagree >{CONFLICT_TOLERANCE*10000:.0f}bp — keep newer, badge + score ×0.5",
        },
        "scale": {
            "ingest": "Per distinct symbol; LiveBus fan-out",
            "hot_cold": f"top-decile watchers poll {settings.hot_poll_seconds}s; rest {settings.cold_poll_seconds}s",
            "dedup": "same-type events within 5m collapse with count",
            "union_symbols_now": len(union),
            "watchlist_cap": settings.max_watchlist,
        },
        "simple_vs_complex": {
            "kept_simple": "RuleBasedScorer via Scorer protocol; one weather/crop overlay; JWT stub",
            "pluggable": "scorer is pluggable by design; ML is natural v2 without touching ingest/digest",
        },
        "default_watchlist": DEFAULT_WATCHLIST,
    }


@router.get("/me")
async def me(x_user_id: Optional[str] = Header(default="demo")):
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    cur = await db.execute("SELECT last_seen_ts, created_at FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    symbols = await get_watchlist(db, user_id)
    await db.close()
    return {
        "user_id": user_id,
        "last_seen_ts": row["last_seen_ts"] if row else 0,
        "watchlist_count": len(symbols),
        "max_watchlist": settings.max_watchlist,
    }
