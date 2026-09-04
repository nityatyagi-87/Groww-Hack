"""Continuous price ingestion + inline significance scoring."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

import aiosqlite

from app.bus import bus
from app.config import settings
from app.db import (
    all_watched_symbols,
    get_db,
    insert_event,
    recent_headline_for_symbol,
    symbol_watcher_counts,
    upsert_quote,
)
from app.scoring import (
    CONFLICT_TOLERANCE,
    CORROBORATION_BOOST,
    DIGEST_SCORE_FLOOR,
    VOLUME_CONFIRM_MIN,
    EventType,
    active_scorer,
    apply_freshness_to_score,
    classify_quote_age,
    resolve_price_conflict,
    score_gap,
    score_micro,
    score_session,
    z_score,
)
from app.seed import BASE_QUOTES


class PriceWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._session_emitted: set[str] = set()
        self._gap_emitted: set[str] = set()
        self._rng = random.Random(42)
        self._alt_source: dict[str, dict] = {}
        # Param 5 — per-symbol last poll for hot/cold tiering
        self._last_tick: dict[str, float] = {}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick_cycle()
            except Exception as e:
                print(f"[price-worker] {e}")
            # Loop often; per-symbol interval decides who ticks (Param 5)
            await asyncio.sleep(1.0)

    def _hot_set(self, counts: dict[str, int]) -> set[str]:
        if not counts:
            return set()
        ranked = sorted(counts.keys(), key=lambda s: counts[s], reverse=True)
        n = max(1, len(ranked) // 10)  # top decile
        return set(ranked[:n])

    async def _tick_cycle(self) -> None:
        db = await get_db()
        symbols = await all_watched_symbols(db)
        if not symbols:
            symbols = list(BASE_QUOTES.keys())[:12]

        counts = await symbol_watcher_counts(db)
        hot = self._hot_set(counts)
        now = time.time()

        nifty = bus.latest.get("NIFTY") or {}
        nifty_day = float(nifty.get("day_pct") or 0.4)

        for sym in symbols:
            # Param 5 — hot/cold data tiering by watcher count
            interval = (
                settings.hot_poll_seconds if sym in hot else settings.cold_poll_seconds
            )
            if now - self._last_tick.get(sym, 0) < interval:
                continue
            self._last_tick[sym] = now

            q = await self._next_quote(db, sym)
            alt_px = q["price"] * (1 + self._rng.uniform(-0.004, 0.004))
            if self._rng.random() < 0.08:
                alt_px = q["price"] * (
                    1 + self._rng.choice([-1, 1]) * self._rng.uniform(0.002, 0.006)
                )
            alt_ts = time.time() - self._rng.uniform(0, 5)
            self._alt_source[sym] = {"price": alt_px, "ts": alt_ts, "source": "shadow"}

            px, ts, conflict, delta = resolve_price_conflict(
                q["price"], q["ts"], alt_px, alt_ts
            )
            q["price"] = px
            q["ts"] = ts
            q["day_pct"] = round((px - q["prev_close"]) / q["prev_close"] * 100, 3)

            delay = 0.0
            if self._rng.random() < 0.03:
                delay = self._rng.choice([25.0, 45.0, 150.0])
            if delay and not conflict:
                q["ts"] = time.time() - delay
            age = max(0.0, time.time() - q["ts"])
            freshness = classify_quote_age(age, bus.market_open)
            if conflict:
                freshness = conflict
                q["conflict_delta"] = round((delta or 0) * 10000, 1)
                print(
                    f"[conflict] {sym} delta={q['conflict_delta']}bp "
                    f"tol={CONFLICT_TOLERANCE*10000:.0f}bp — keeping newer source"
                )
            q["freshness"] = freshness.value
            q["age_s"] = round(age, 1)
            await upsert_quote(db, q)
            await bus.publish_tick(sym, q)

            if freshness.value == "STALE":
                continue

            gap_key = f"gap:{sym}:{time.strftime('%Y%m%d')}"
            gap_pct = (q["day_open"] - q["prev_close"]) / q["prev_close"] * 100
            if gap_key not in self._gap_emitted and abs(gap_pct) >= settings.gap_pct:
                sb = score_gap(gap_pct)
                # Param 4 — freshness into scorer before threshold
                eff = apply_freshness_to_score(sb.total, freshness.value)
                if eff >= 30:
                    eid = await insert_event(
                        db,
                        symbol=sym,
                        event_type=EventType.OPEN_GAP.value,
                        score=eff,
                        magnitude=sb.magnitude,
                        unusualness=sb.unusualness,
                        corroboration=sb.corroboration,
                        freshness=sb.freshness,
                        payload={"gap_pct": round(gap_pct, 2), "freshness": freshness.value},
                    )
                    if eid > 0:
                        self._gap_emitted.add(gap_key)
                        await bus.publish_event(
                            {
                                "id": eid,
                                "symbol": sym,
                                "event_type": EventType.OPEN_GAP.value,
                                "score": eff,
                            }
                        )

            window = list(bus.ticks[sym])
            hl = await recent_headline_for_symbol(db, sym)
            tick = {
                **q,
                "has_headline": bool(hl),
                "freshness": freshness.value,
            }
            # Param 6 — pluggable scorer; Param 1/4 inside RuleBasedScorer.score
            sig = active_scorer.score(tick, window)
            if sig >= DIGEST_SCORE_FLOOR:
                # Recover z/vol for payload (scorer already gated on threshold)
                rets = []
                for i in range(1, len(window)):
                    prev, cur = window[i - 1], window[i]
                    if prev > 0:
                        rets.append((cur - prev) / prev * 100)
                latest_ret = rets[-1] if rets else 0.0
                z = z_score(rets[:-1], latest_ret) if len(rets) >= 5 else 0.0
                vol_ratio = q["volume"] / max(q["avg_volume"], 1)
                sb = score_micro(z, vol_ratio)
                payload = {
                    "move_pct": round(latest_ret, 3),
                    "z": round(z, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "has_headline": bool(hl),
                    "price": q["price"],
                    "freshness": freshness.value,
                }
                if hl and vol_ratio >= VOLUME_CONFIRM_MIN:
                    payload["corroborated"] = True
                    payload["corroboration_model"] = (
                        f"price+volume+headline ×{CORROBORATION_BOOST}"
                    )
                    if hl.get("title"):
                        payload["headline"] = hl["title"]
                eid = await insert_event(
                    db,
                    symbol=sym,
                    event_type=EventType.MICRO_SPIKE.value,
                    score=sig,
                    magnitude=sb.magnitude,
                    unusualness=sb.unusualness,
                    corroboration=sb.corroboration,
                    freshness=sb.freshness,
                    payload=payload,
                )
                if eid > 0:
                    await bus.publish_event(
                        {
                            "id": eid,
                            "symbol": sym,
                            "event_type": EventType.MICRO_SPIKE.value,
                            "score": sig,
                        }
                    )

            day_pct = q["day_pct"]
            key = f"{sym}:{time.strftime('%Y%m%d')}"
            if (
                key not in self._session_emitted
                and abs(day_pct) >= settings.session_move_pct
                and abs(day_pct) < 25
            ):
                residual = day_pct - nifty_day
                sb = score_session(day_pct, q["atr_pct"], residual)
                eff = apply_freshness_to_score(sb.total, freshness.value)
                if eff >= 40:
                    eid = await insert_event(
                        db,
                        symbol=sym,
                        event_type=EventType.SESSION_MOVE.value,
                        score=eff,
                        magnitude=sb.magnitude,
                        unusualness=sb.unusualness,
                        corroboration=sb.corroboration,
                        freshness=sb.freshness,
                        payload={
                            "day_pct": round(day_pct, 2),
                            "atr_pct": q["atr_pct"],
                            "residual": round(residual, 2),
                            "freshness": freshness.value,
                        },
                    )
                    if eid > 0:
                        self._session_emitted.add(key)
                        await bus.publish_event(
                            {
                                "id": eid,
                                "symbol": sym,
                                "event_type": EventType.SESSION_MOVE.value,
                                "score": eff,
                            }
                        )
        await db.close()

    async def _next_quote(self, db: aiosqlite.Connection, sym: str) -> dict:
        cur = await db.execute("SELECT * FROM quotes WHERE symbol=?", (sym,))
        row = await cur.fetchone()
        base = BASE_QUOTES.get(sym, {"price": 1000.0, "atr_pct": 1.5})
        anchor_px = float(base["price"])
        atr = float(base["atr_pct"])

        if row:
            price = float(row["price"])
            prev = float(row["prev_close"])
            day_open = float(row["day_open"])
            avg_vol = float(row["avg_volume"]) or 1_000_000.0
            if not (0.5 * anchor_px < price < 1.5 * anchor_px):
                price = anchor_px
                prev = anchor_px * 0.992
                day_open = anchor_px * 0.995
        else:
            price = anchor_px
            prev = anchor_px * 0.992
            day_open = anchor_px * 0.995
            avg_vol = 1_000_000.0

        sigma = (atr / 100.0) / 8.0
        shock = self._rng.gauss(0.0, sigma)
        if self._rng.random() < 0.035:
            shock += self._rng.choice([-1.0, 1.0]) * (atr / 100.0) * self._rng.uniform(0.5, 1.1)
            vol = avg_vol * self._rng.uniform(1.4, 2.1)
        else:
            vol = avg_vol * self._rng.uniform(0.9, 1.15)

        shock = max(-0.012, min(0.012, shock))
        price = price * (1.0 + shock) + (day_open - price) * 0.01
        lo, hi = prev * 0.92, prev * 1.08
        price = max(lo, min(hi, price))
        price = round(price, 2)
        day_pct = round((price - prev) / prev * 100.0, 3)

        return {
            "symbol": sym,
            "price": price,
            "prev_close": round(prev, 2),
            "day_open": round(day_open, 2),
            "volume": round(vol),
            "avg_volume": avg_vol,
            "atr_pct": atr,
            "ts": time.time(),
            "source": "demo",
            "day_pct": day_pct,
        }
