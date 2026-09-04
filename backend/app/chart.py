"""Deterministic OHLC series for symbol detail charts (demo-grade, live-pinned)."""
from __future__ import annotations

import hashlib
import random
import time
from typing import Literal

from app.seed import BASE_QUOTES

Timeframe = Literal["1D", "1W", "1M", "3M", "1Y"]

TF_SPEC: dict[str, dict] = {
    # bars, seconds per bar, label
    "1D": {"bars": 78, "step": 5 * 60, "label": "Today · 5m"},
    "1W": {"bars": 35, "step": 60 * 60, "label": "1W · 1h"},
    "1M": {"bars": 30, "step": 24 * 60 * 60, "label": "1M · 1d"},
    "3M": {"bars": 65, "step": 24 * 60 * 60, "label": "3M · 1d"},
    "1Y": {"bars": 52, "step": 7 * 24 * 60 * 60, "label": "1Y · 1w"},
}


def _rng(symbol: str, tf: str) -> random.Random:
    h = hashlib.sha256(f"{symbol}:{tf}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def build_ohlc(
    symbol: str,
    tf: Timeframe = "1D",
    live_price: float | None = None,
) -> dict:
    if symbol not in BASE_QUOTES:
        raise KeyError(symbol)
    spec = TF_SPEC[tf]
    n = spec["bars"]
    step = spec["step"]
    atr = BASE_QUOTES[symbol]["atr_pct"] / 100.0
    base = BASE_QUOTES[symbol]["price"]
    px = live_price if live_price and live_price > 0 else base
    rng = _rng(symbol, tf)

    # Walk backward from now so the last bar pins to live price
    now = time.time()
    # Start price roughly near live, with mild drift history
    start = px * (1.0 - rng.uniform(-0.04, 0.06))
    path = [start]
    for i in range(1, n):
        shock = rng.gauss(0, atr / (3 if tf == "1D" else 2))
        # occasional larger day moves on longer TFs
        if tf != "1D" and rng.random() < 0.08:
            shock += rng.choice([-1, 1]) * atr * rng.uniform(0.8, 1.8)
        nxt = path[-1] * (1.0 + max(-0.04, min(0.04, shock)))
        path.append(nxt)

    # Affine scale so last close ~= live price
    scale = px / path[-1]
    path = [p * scale for p in path]

    candles = []
    for i, close in enumerate(path):
        open_ = path[i - 1] if i else close * (1 + rng.uniform(-0.002, 0.002))
        hi = max(open_, close) * (1 + abs(rng.gauss(0, atr * 0.25)))
        lo = min(open_, close) * (1 - abs(rng.gauss(0, atr * 0.25)))
        vol = int(BASE_QUOTES[symbol]["price"] * rng.uniform(80, 220))  # proxy units
        ts = now - (n - 1 - i) * step
        candles.append(
            {
                "t": ts,
                "o": round(open_, 2),
                "h": round(hi, 2),
                "l": round(lo, 2),
                "c": round(close, 2),
                "v": vol,
            }
        )

    first, last = candles[0]["c"], candles[-1]["c"]
    change_pct = ((last - first) / first) * 100 if first else 0.0
    return {
        "symbol": symbol,
        "tf": tf,
        "label": spec["label"],
        "currency": "INR",
        "last": last,
        "change_pct": round(change_pct, 2),
        "candles": candles,
        "line": [{"t": c["t"], "v": c["c"]} for c in candles],
    }
