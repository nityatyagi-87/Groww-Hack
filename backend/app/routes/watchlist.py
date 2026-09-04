from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.bus import bus
from app.config import settings
from app.db import ensure_user, get_db, get_watchlist
from app.scoring import classify_quote_age
from app.seed import BASE_QUOTES
from app.routes.digest import uid

router = APIRouter(prefix="/api", tags=["watchlist"])


class SymbolBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)


@router.get("/watchlist")
async def list_watchlist(x_user_id: Optional[str] = Header(default="demo")):
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    symbols = await get_watchlist(db, user_id)
    if not symbols:
        return {"user_id": user_id, "symbols": [], "quotes": []}
    placeholders = ",".join("?" * len(symbols))
    cur = await db.execute(
        f"SELECT * FROM quotes WHERE symbol IN ({placeholders})", symbols
    )
    quotes = [dict(r) for r in await cur.fetchall()]
    # preserve watchlist order
    by = {q["symbol"]: q for q in quotes}
    ordered = []
    for s in symbols:
        q = by.get(s)
        if not q:
            base = BASE_QUOTES.get(s, {"price": 0, "atr_pct": 1.5})
            q = {
                "symbol": s,
                "price": base["price"],
                "prev_close": base["price"],
                "day_open": base["price"],
                "volume": 0,
                "avg_volume": 0,
                "atr_pct": base["atr_pct"],
                "ts": time.time(),
                "source": "pending",
                "day_pct": 0,
            }
        else:
            q["day_pct"] = round((q["price"] - q["prev_close"]) / q["prev_close"] * 100, 3)
        age = max(0.0, time.time() - float(q.get("ts") or time.time()))
        live = bus.latest.get(s, {})
        if live.get("freshness"):
            q["freshness"] = live["freshness"]
        else:
            q["freshness"] = classify_quote_age(age, bus.market_open).value
        q["age_s"] = round(age, 1)
        ordered.append(q)
    await db.close()
    return {
        "user_id": user_id,
        "symbols": symbols,
        "quotes": ordered,
        "max_watchlist": settings.max_watchlist,
    }


@router.post("/watchlist")
async def add_symbol(body: SymbolBody, x_user_id: Optional[str] = Header(default="demo")):
    user_id = uid(x_user_id)
    sym = body.symbol.upper().strip()
    if sym not in BASE_QUOTES:
        raise HTTPException(400, f"Unknown symbol. Universe: {', '.join(sorted(BASE_QUOTES)[:12])}…")
    db = await get_db()
    await ensure_user(db, user_id)
    existing = await get_watchlist(db, user_id)
    if sym not in existing and len(existing) >= settings.max_watchlist:
        await db.close()
        raise HTTPException(400, f"Watchlist cap {settings.max_watchlist} — remove a symbol first")
    await db.execute(
        "INSERT OR IGNORE INTO watchlist_items(user_id,symbol,added_at) VALUES(?,?,?)",
        (user_id, sym, time.time()),
    )
    await db.commit()
    symbols = await get_watchlist(db, user_id)
    await db.close()
    return {"symbols": symbols}


@router.delete("/watchlist/{symbol}")
async def remove_symbol(symbol: str, x_user_id: Optional[str] = Header(default="demo")):
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    await db.execute(
        "DELETE FROM watchlist_items WHERE user_id=? AND symbol=?",
        (user_id, symbol.upper()),
    )
    await db.commit()
    symbols = await get_watchlist(db, user_id)
    await db.close()
    return {"symbols": symbols}


@router.get("/universe")
async def universe():
    return {"symbols": sorted(BASE_QUOTES.keys())}


@router.get("/context")
async def overnight_context():
    """World-monitor-style overnight tape for Indian books."""
    return {
        "as_of": time.time(),
        "tape": [
            {"label": "Nasdaq", "value": "-1.8%", "tone": "neg"},
            {"label": "S&P 500", "value": "-1.1%", "tone": "neg"},
            {"label": "USD/INR", "value": "83.72", "tone": "neg"},
            {"label": "Brent", "value": "+3.0%", "tone": "pos"},
            {"label": "India VIX", "value": "13.4", "tone": "neu"},
        ],
        "regime": "SESSION_SIM",
        "note": "US soft + crude spike — IT & energy books most exposed",
    }
