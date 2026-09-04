from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect

from app.bus import bus
from app.db import ensure_user, get_db, get_watchlist
from app.routes.digest import uid

router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    user_id = ws.query_params.get("user") or "demo"
    db = await get_db()
    await ensure_user(db, user_id)
    symbols = await get_watchlist(db, user_id)
    await db.close()
    if not symbols:
        await ws.send_json({"type": "error", "message": "empty watchlist"})
        await ws.close()
        return

    q = bus.subscribe(symbols)
    await ws.send_json({"type": "subscribed", "symbols": symbols})
    # Push latest snapshot
    for s in symbols:
        if s in bus.latest:
            await ws.send_json({"type": "tick", "data": bus.latest[s]})

    async def reader():
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=25)
                kind = "event" if item["channel"] == "event" else "tick"
                await ws.send_json({"type": kind, "data": item["data"]})
            except asyncio.TimeoutError:
                await ws.send_json({"type": "heartbeat", "market_open": bus.market_open})
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        bus.unsubscribe(q, symbols)


@router.get("/api/headlines")
async def headlines(x_user_id: Optional[str] = Header(default="demo"), limit: int = 30):
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    symbols = set(await get_watchlist(db, user_id))
    cur = await db.execute(
        "SELECT * FROM headlines ORDER BY ts DESC LIMIT ?", (limit * 2,)
    )
    rows = await cur.fetchall()
    out = []
    for r in rows:
        syms = json.loads(r["symbols"])
        hit = [s for s in syms if s in symbols]
        if not hit and symbols:
            continue
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "kind": r["kind"],
                "sectors": json.loads(r["sectors"]),
                "symbols": hit or syms[:4],
                "ts": r["ts"],
            }
        )
        if len(out) >= limit:
            break
    await db.close()
    return {"items": out}
