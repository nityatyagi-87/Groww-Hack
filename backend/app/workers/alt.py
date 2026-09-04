"""Emit LAG_ALERT events when alt disruption >> price move."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.alt_data import lag_alert_candidates
from app.bus import bus
from app.db import get_db, insert_event
from app.scoring import EventType


class AltWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(3)
        while True:
            try:
                await self._cycle()
            except Exception as e:
                print(f"[alt-worker] {e}")
            await asyncio.sleep(60)

    async def _cycle(self) -> None:
        day = {s: float(q.get("day_pct") or 0) for s, q in bus.latest.items()}
        db = await get_db()
        for a in lag_alert_candidates(day):
            # One LAG per symbol per hour
            cur = await db.execute(
                "SELECT id FROM events WHERE symbol=? AND event_type=? AND ts > ? LIMIT 1",
                (a["symbol"], EventType.LAG_ALERT.value, time.time() - 3600),
            )
            if await cur.fetchone():
                continue
            eid = await insert_event(
                db,
                symbol=a["symbol"],
                event_type=EventType.LAG_ALERT.value,
                score=a["score"],
                magnitude=a["score"] * 0.5,
                unusualness=a["score"] * 0.35,
                corroboration=55.0,
                freshness=8.0,
                payload=a["payload"],
                ts=time.time(),
            )
            if eid > 0:
                await bus.publish_event(
                    {
                        "id": eid,
                        "symbol": a["symbol"],
                        "event_type": EventType.LAG_ALERT.value,
                        "score": a["score"],
                    }
                )
        await db.close()
