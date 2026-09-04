"""Seed universe + demo baseline quotes / overnight catalysts."""
from __future__ import annotations

import time
from typing import Any

from app.db import ensure_user, get_db, insert_event, insert_headline, upsert_quote
from app.scoring import EventType, SECTOR_SYMBOLS, score_catalyst, score_gap, score_session

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "TATAMOTORS", "ITC", "DMART", "ONGC", "M&M",
]

# Approx INR levels for demo realism
BASE_QUOTES: dict[str, dict[str, float]] = {
    "RELIANCE": {"price": 2980, "atr_pct": 1.6},
    "TCS": {"price": 4120, "atr_pct": 1.2},
    "INFY": {"price": 1885, "atr_pct": 1.4},
    "WIPRO": {"price": 265, "atr_pct": 1.5},
    "HCLTECH": {"price": 1780, "atr_pct": 1.3},
    "HDFCBANK": {"price": 1685, "atr_pct": 1.1},
    "ICICIBANK": {"price": 1240, "atr_pct": 1.3},
    "SBIN": {"price": 820, "atr_pct": 1.5},
    "KOTAKBANK": {"price": 1785, "atr_pct": 1.2},
    "MARUTI": {"price": 12500, "atr_pct": 1.4},
    "TATAMOTORS": {"price": 780, "atr_pct": 2.0},
    "M&M": {"price": 2850, "atr_pct": 1.7},
    "ITC": {"price": 475, "atr_pct": 1.3},
    "DMART": {"price": 3850, "atr_pct": 1.6},
    "TRENT": {"price": 6200, "atr_pct": 1.8},
    "ONGC": {"price": 285, "atr_pct": 2.2},
    "BPCL": {"price": 310, "atr_pct": 2.0},
    "IOC": {"price": 145, "atr_pct": 2.1},
    "SUNPHARMA": {"price": 1780, "atr_pct": 1.3},
    "DRREDDY": {"price": 1280, "atr_pct": 1.4},
    "CIPLA": {"price": 1490, "atr_pct": 1.3},
    "TATASTEEL": {"price": 155, "atr_pct": 2.3},
    "HINDALCO": {"price": 680, "atr_pct": 2.1},
    "JSWSTEEL": {"price": 920, "atr_pct": 2.0},
    "INDIGO": {"price": 4350, "atr_pct": 2.4},
    "HAL": {"price": 4680, "atr_pct": 2.5},
    "BEL": {"price": 285, "atr_pct": 2.2},
    "ASIANPAINT": {"price": 2480, "atr_pct": 1.2},
    "NIFTY": {"price": 24850, "atr_pct": 0.8},
    "BANKNIFTY": {"price": 51200, "atr_pct": 1.0},
    # Misc / midcap / commodities-linked
    "ZOMATO": {"price": 245, "atr_pct": 2.8},
    "PAYTM": {"price": 780, "atr_pct": 3.0},
    "NYKAA": {"price": 175, "atr_pct": 2.5},
    "IRCTC": {"price": 820, "atr_pct": 2.2},
    "LT": {"price": 3580, "atr_pct": 1.5},
    "BHARTIARTL": {"price": 1650, "atr_pct": 1.6},
    "ADANIENT": {"price": 2680, "atr_pct": 2.8},
    "COALINDIA": {"price": 420, "atr_pct": 2.0},
    "POWERGRID": {"price": 310, "atr_pct": 1.4},
    "NTPC": {"price": 365, "atr_pct": 1.5},
    "BAJFINANCE": {"price": 7200, "atr_pct": 2.1},
    "TITAN": {"price": 3450, "atr_pct": 1.7},
    "ULTRACEMCO": {"price": 11200, "atr_pct": 1.6},
    "GOLD": {"price": 74500, "atr_pct": 1.1},
    "SILVER": {"price": 89000, "atr_pct": 1.8},
    "USDINR": {"price": 83.7, "atr_pct": 0.4},
    # US overnight indexes (chartable)
    "NDX": {"price": 17850, "atr_pct": 1.2},
    "SPX": {"price": 5420, "atr_pct": 1.0},
    "DJI": {"price": 39850, "atr_pct": 0.9},
}

DEMO_HEADLINES = [
    {
        "title": "Nasdaq closes -1.8% as Fed officials signal higher-for-longer rates",
        "source": "US Wire",
        "kind": "US_MACRO",
        "sectors": ["it"],
        "symbols": SECTOR_SYMBOLS["it"],
    },
    {
        "title": "Brent crude jumps 3% after Red Sea tanker disruption near Hormuz approaches",
        "source": "Geo Desk",
        "kind": "GEO",
        "sectors": ["energy", "aviation"],
        "symbols": SECTOR_SYMBOLS["energy"] + SECTOR_SYMBOLS["aviation"],
    },
    {
        "title": "FII selling streak hits banking names; Rupee softens vs dollar",
        "source": "India Macro",
        "kind": "US_MACRO",
        "sectors": ["banking"],
        "symbols": SECTOR_SYMBOLS["banking"],
    },
    {
        "title": "Defence ministry clears additional orders; HAL, BEL in focus",
        "source": "Sector",
        "kind": "SECTOR",
        "sectors": ["defence"],
        "symbols": SECTOR_SYMBOLS["defence"],
    },
]


async def seed(force: bool = False) -> None:
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) AS c FROM quotes")
    row = await cur.fetchone()
    if row["c"] > 0 and not force:
        await db.close()
        return

    now = time.time()
    for sym, meta in BASE_QUOTES.items():
        px = meta["price"]
        q: dict[str, Any] = {
            "symbol": sym,
            "price": px,
            "prev_close": px * 0.992,
            "day_open": px * 0.995,
            "volume": 1_000_000,
            "avg_volume": 1_000_000,
            "atr_pct": meta["atr_pct"],
            "ts": now,
            "source": "demo",
        }
        await upsert_quote(db, q)

    # Demo user + watchlist
    uid = "demo"
    await ensure_user(db, uid)
    await db.execute("DELETE FROM watchlist_items WHERE user_id=?", (uid,))
    for i, sym in enumerate(DEFAULT_WATCHLIST):
        await db.execute(
            "INSERT OR IGNORE INTO watchlist_items(user_id,symbol,added_at) VALUES(?,?,?)",
            (uid, sym, now - 86400 + i),
        )
    # last_seen ~14h ago so overnight catalysts appear in digest
    await db.execute("UPDATE users SET last_seen_ts=? WHERE id=?", (now - 14 * 3600, uid))
    await db.commit()

    # Seed overnight events for a rich first digest
    for h in DEMO_HEADLINES:
        h = {**h, "ts": now - 10 * 3600, "url": None}
        await insert_headline(db, h)
        sb = score_catalyst(h["kind"], 2, has_price_move=True)
        for sym in h["symbols"]:
            if sym not in DEFAULT_WATCHLIST and sym not in ("BPCL", "IOC", "INDIGO", "BEL", "WIPRO"):
                continue
            if sym not in DEFAULT_WATCHLIST:
                continue
            await insert_event(
                db,
                symbol=sym,
                event_type=EventType.CATALYST.value,
                score=sb.total,
                magnitude=sb.magnitude,
                unusualness=sb.unusualness,
                corroboration=sb.corroboration,
                freshness=sb.freshness,
                payload={"kind": h["kind"], "headline": h["title"], "source": h["source"]},
                ts=now - 10 * 3600,
            )

    # Session / gap / lag seeds
    seeds = [
        ("RELIANCE", EventType.OPEN_GAP, {"gap_pct": 2.1}, score_gap(2.1), now - 5 * 3600),
        ("INFY", EventType.SESSION_MOVE, {"day_pct": -2.4, "atr_pct": 1.4, "residual": -2.0},
         score_session(-2.4, 1.4, -2.0), now - 3 * 3600),
        ("ITC", EventType.SESSION_MOVE, {"day_pct": -0.4, "atr_pct": 1.3, "residual": -0.6},
         score_session(-0.4, 1.3, -0.6), now - 2 * 3600),
        ("ONGC", EventType.SESSION_MOVE, {"day_pct": 2.8, "atr_pct": 2.2, "residual": 2.4},
         score_session(2.8, 2.2, 2.4), now - 4 * 3600),
    ]
    for sym, et, payload, sb, ts in seeds:
        await insert_event(
            db,
            symbol=sym,
            event_type=et.value,
            score=sb.total,
            magnitude=sb.magnitude,
            unusualness=sb.unusualness,
            corroboration=sb.corroboration,
            freshness=sb.freshness,
            payload=payload,
            ts=ts,
        )

    # Seed lag alerts — disruption ahead of price
    lag_seeds = [
        ("TATAMOTORS", "PORT_CONGESTION", "Satellite port congestion elevated", "JNPT / Mundra"),
        ("ITC", "EXTREME_WEATHER", "Extreme weather stress in ag belt", "Maharashtra belt"),
        ("DMART", "REGIONAL_STRIKE", "Logistics delay spike (corridor risk)", "West coast"),
        ("M&M", "EXTREME_WEATHER", "Crop yield estimate soft + weather stress", "Kharif belt"),
    ]
    for sym, kind, title, region in lag_seeds:
        await insert_event(
            db,
            symbol=sym,
            event_type=EventType.LAG_ALERT.value,
            score=78.0,
            magnitude=40.0,
            unusualness=32.0,
            corroboration=55.0,
            freshness=8.0,
            payload={
                "kind": kind,
                "headline": title,
                "region": region,
                "severity": 0.72,
                "day_pct": 0.3,
                "note": "Local disruption not yet in share price — earnings risk",
            },
            ts=now - 1.5 * 3600,
        )

    await db.close()
