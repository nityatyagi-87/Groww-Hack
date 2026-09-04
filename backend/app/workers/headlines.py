"""Headline ingestion + catalyst event emission."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.bus import bus
from app.config import settings
from app.db import boost_recent_price_event, get_db, insert_event, insert_headline
from app.scoring import CORROBORATION_BOOST, EventType, match_headline, score_catalyst
from app.seed import DEMO_HEADLINES

ROTATING = [
    *DEMO_HEADLINES,
    {
        "title": "S&P futures soft overnight; IT exporters may open weak on NSE",
        "source": "US Wire",
        "kind": "US_MACRO",
        "sectors": ["it"],
    },
    {
        "title": "Ukraine drone strikes renew energy security premium on crude",
        "source": "Geo Desk",
        "kind": "GEO",
        "sectors": ["energy"],
    },
    {
        "title": "Celebrity wedding week draws TV TRPs",  # denied
        "source": "Noise",
        "kind": "SECTOR",
        "sectors": [],
    },
]


class HeadlineWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._i = 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self._emit_one()
            except Exception as e:
                print(f"[headline-worker] {e}")
            await asyncio.sleep(settings.headline_poll_seconds)

    async def _emit_one(self) -> None:
        raw = ROTATING[self._i % len(ROTATING)]
        self._i += 1
        matches = match_headline(raw["title"])
        if not matches:
            return
        db = await get_db()
        symbols: list[str] = []
        sectors: list[str] = []
        kind = raw.get("kind", "SECTOR")
        for sector, k, syms in matches:
            sectors.append(sector)
            kind = k
            symbols.extend(syms)
        symbols = sorted(set(symbols))
        now = time.time()
        await insert_headline(
            db,
            {
                "title": raw["title"],
                "source": raw["source"],
                "url": None,
                "kind": kind,
                "sectors": sectors,
                "symbols": symbols,
                "ts": now,
            },
        )
        for sym in symbols:
            # Corroboration model: fold into recent price event instead of 2nd card
            folded = await boost_recent_price_event(
                db, sym, raw["title"], CORROBORATION_BOOST
            )
            if folded:
                await bus.publish_event(
                    {
                        "id": folded,
                        "symbol": sym,
                        "event_type": EventType.MICRO_SPIKE.value,
                        "score": 0,
                        "corroborated": True,
                    }
                )
                continue
            day = abs(bus.latest.get(sym, {}).get("day_pct", 0) or 0)
            sb = score_catalyst(kind, max(1, len(sectors)), has_price_move=day >= 1.0)
            if sb.total < 30:
                continue
            eid = await insert_event(
                db,
                symbol=sym,
                event_type=EventType.CATALYST.value,
                score=sb.total,
                magnitude=sb.magnitude,
                unusualness=sb.unusualness,
                corroboration=sb.corroboration,
                freshness=sb.freshness,
                payload={
                    "kind": kind,
                    "headline": raw["title"],
                    "source": raw["source"],
                    "freshness": "LIVE",
                },
            )
            if eid > 0:
                await bus.publish_event(
                    {
                        "id": eid,
                        "symbol": sym,
                        "event_type": EventType.CATALYST.value,
                        "score": sb.total,
                    }
                )
        await db.close()
