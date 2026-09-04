"""In-process pub/sub + rolling tick windows (Redis role, no ops tax)."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any, Deque, DefaultDict, Set

from app.config import settings


class LiveBus:
    def __init__(self) -> None:
        self._subs: DefaultDict[str, Set[asyncio.Queue]] = defaultdict(set)
        self.ticks: DefaultDict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=settings.tick_window)
        )
        self.volumes: DefaultDict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=settings.tick_window)
        )
        self.latest: dict[str, dict[str, Any]] = {}
        self.market_open: bool = True
        self.lock = asyncio.Lock()

    def subscribe(self, symbols: list[str]) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        for s in symbols:
            self._subs[s].add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, symbols: list[str]) -> None:
        for s in symbols:
            self._subs[s].discard(q)

    async def publish_tick(self, symbol: str, payload: dict[str, Any]) -> None:
        self.ticks[symbol].append(payload["price"])
        self.volumes[symbol].append(payload.get("volume", 0))
        self.latest[symbol] = payload
        dead = []
        for q in list(self._subs.get(symbol, ())):
            try:
                q.put_nowait({"channel": f"price:{symbol}", "data": payload})
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subs[symbol].discard(q)

    async def publish_event(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol")
        if not symbol:
            return
        for q in list(self._subs.get(symbol, ())):
            try:
                q.put_nowait({"channel": "event", "data": payload})
            except asyncio.QueueFull:
                pass


bus = LiveBus()
