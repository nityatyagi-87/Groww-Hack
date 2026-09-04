"""ONE alt overlay: weather/crop (Param 2/6). Lag when disruption ≫ price (Param 1)."""
from __future__ import annotations

import hashlib
import random
import time
from typing import Any

# Only agri-exposed names get the single weather/crop overlay
SYMBOL_EXPOSURE: dict[str, dict[str, Any]] = {
    "M&M": {"sectors": ["agri", "auto"], "overlays": ["weather_crop"]},
    "ITC": {"sectors": ["agri"], "overlays": ["weather_crop"]},
}

OVERLAY_META = {
    "weather_crop": {
        "label": "Weather / crop stress",
        "unit": "index",
        "bullish_when": "down",
    },
}

US_INDEXES = [
    {"symbol": "NDX", "name": "Nasdaq", "base": 17850.0, "day": -1.8},
    {"symbol": "SPX", "name": "S&P 500", "base": 5420.0, "day": -1.1},
    {"symbol": "DJI", "name": "Dow", "base": 39850.0, "day": -0.7},
]


def _rng(key: str) -> random.Random:
    return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


def factor_snapshot(now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    r = _rng(f"wx:{int(now // 300)}")
    wx = round(55 + r.uniform(0, 35), 1)
    factors = {
        "weather_crop": {
            "id": "weather_crop",
            "label": OVERLAY_META["weather_crop"]["label"],
            "value": wx,
            "delta": round(r.uniform(5, 18), 1),
            "region": "Maharashtra / Kharif belt",
            "freshness": "LIVE" if wx < 80 else "DELAYED",
            "age_s": 8,
            "source": "wx_crop_demo",
        }
    }
    disruptions = []
    if wx >= 60:
        disruptions.append(
            {
                "id": "wx_crop",
                "kind": "EXTREME_WEATHER",
                "title": "Weather/crop stress elevated",
                "region": factors["weather_crop"]["region"],
                "severity": min(1.0, wx / 100),
                "overlays": ["weather_crop"],
            }
        )
    return {"ts": now, "factors": factors, "disruptions": disruptions}


def overlay_series(symbol: str, n: int = 40) -> list[dict]:
    exp = SYMBOL_EXPOSURE.get(symbol)
    if not exp:
        return []
    now = time.time()
    r = _rng(f"{symbol}:weather_crop")
    v = 55.0
    pts = []
    for i in range(n):
        v += r.gauss(0, 1.2)
        pts.append({"t": now - (n - 1 - i) * 3600, "v": round(v, 2)})
    return [
        {
            "id": "weather_crop",
            "label": OVERLAY_META["weather_crop"]["label"],
            "unit": "index",
            "points": pts,
        }
    ]


def lag_alert_candidates(day_pct_by_symbol: dict[str, float]) -> list[dict]:
    snap = factor_snapshot()
    alerts = []
    for d in snap["disruptions"]:
        for sym, exp in SYMBOL_EXPOSURE.items():
            if not set(d["overlays"]) & set(exp["overlays"]):
                continue
            day = abs(day_pct_by_symbol.get(sym, 0.0))
            if d["severity"] >= 0.55 and day < 1.2:
                score = round(40 + d["severity"] * 45 + (1.2 - day) * 10, 1)
                alerts.append(
                    {
                        "symbol": sym,
                        "event_type": "LAG_ALERT",
                        "score": min(98.0, score),
                        "payload": {
                            "kind": d["kind"],
                            "headline": d["title"],
                            "region": d["region"],
                            "severity": round(d["severity"], 2),
                            "day_pct": day_pct_by_symbol.get(sym, 0.0),
                            "note": "Weather/crop disruption not yet in share price",
                            "freshness": snap["factors"]["weather_crop"]["freshness"],
                        },
                    }
                )
    return alerts


def us_index_sparks() -> list[dict]:
    now = time.time()
    out = []
    for ix in US_INDEXES:
        r = _rng(ix["symbol"])
        n = 48
        px = ix["base"] * (1 + ix["day"] / 100 * 0.4)
        pts = []
        for i in range(n):
            px *= 1 + r.gauss(ix["day"] / 100 / n, 0.0015)
            pts.append({"t": now - (n - 1 - i) * 300, "v": round(px, 2)})
        end = ix["base"] * (1 + ix["day"] / 100)
        scale = end / pts[-1]["v"]
        pts = [{"t": p["t"], "v": round(p["v"] * scale, 2)} for p in pts]
        out.append(
            {
                "symbol": ix["symbol"],
                "name": ix["name"],
                "last": pts[-1]["v"],
                "day_pct": ix["day"],
                "line": pts,
                "freshness": "DELAYED",
            }
        )
    return out
