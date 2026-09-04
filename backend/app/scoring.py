"""
Event taxonomy = answer to Param 1 (meaningful change). Headline of the product.

MICRO_SPIKE   | intraday burst vs own rolling vol (z × volume confirm)
SESSION_MOVE  | session |day%| vs ATR / residual vs Nifty
OPEN_GAP      | open vs prev close discontinuity
CATALYST      | tagged headline linked to symbol
LAG_ALERT     | weather/crop disruption while price still quiet
QUIET         | nothing unread on watchlist

SIGNIFICANCE (Param 1) — documented at RuleBasedScorer.score:
  significance ≈ |z| × volume_confirm × time_decay
  MICRO emits when |z| ≥ MICRO_Z_THRESHOLD (2.0) AND vol_ratio ≥ 1.15
  Why 2.0: ~95% of a symbol's own short-window moves are below 2σ; crossing it
  is unusual *for that stock*, not vs the index. Volume confirm cuts fake prints.

CORROBORATION MODEL (Param 1): when price + volume-confirm + headline all fire on
the same symbol, collapse to one card and boost score × CORROBORATION_BOOST (1.5)
instead of three separate events.

Param 6: Scorer protocol — pluggable; RuleBasedScorer is the only impl for now.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

# Param 1 — threshold constant (see module docstring)
MICRO_Z_THRESHOLD = 2.0
VOLUME_CONFIRM_MIN = 1.15
CORROBORATION_BOOST = 1.5  # price + volume + headline → one higher-confidence card
# Param 1 — sensitivity multiplies the significance *threshold* (stricter vs looser)
SENSITIVITY_THRESHOLD_MULT = {"low": 1.35, "med": 1.0, "high": 0.7}
DIGEST_SCORE_FLOOR = 35.0
# Param 4 — price sources disagree beyond this relative delta → CONFLICT
CONFLICT_TOLERANCE = 0.0015  # 15 bps
# Param 4 — feed freshness into scorer (not cosmetic only)
FRESHNESS_SCORE_WEIGHT = {
    "LIVE": 1.0,
    "DELAYED": 0.5,
    "CONFLICT": 0.5,
    "STALE": 0.0,
    "CLOSED": 0.0,
}
# Param 5 — collapse same-type repeats within this window
DEDUP_WINDOW_S = 300.0


class EventType(str, Enum):
    MICRO_SPIKE = "MICRO_SPIKE"
    SESSION_MOVE = "SESSION_MOVE"
    OPEN_GAP = "OPEN_GAP"
    CATALYST = "CATALYST"
    LAG_ALERT = "LAG_ALERT"
    QUIET = "QUIET"


class DataFreshness(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    CLOSED = "CLOSED"
    CONFLICT = "CONFLICT"


SECTOR_SYMBOLS: dict[str, list[str]] = {
    "energy": ["RELIANCE", "ONGC", "BPCL", "IOC"],
    "it": ["TCS", "INFY", "WIPRO", "HCLTECH"],
    "banking": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"],
    "auto": ["MARUTI", "TATAMOTORS", "M&M"],
    "agri": ["ITC", "M&M"],
    "retail": ["DMART", "TRENT", "RELIANCE"],
    "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA"],
    "metals": ["TATASTEEL", "HINDALCO", "JSWSTEEL"],
    "aviation": ["INDIGO"],
    "defence": ["HAL", "BEL"],
    "paints": ["ASIANPAINT"],
    "index": ["NIFTY", "BANKNIFTY"],
}

SYMBOL_TO_SECTOR: dict[str, str] = {
    sym: sector for sector, syms in SECTOR_SYMBOLS.items() for sym in syms
}

KEYWORD_SECTOR: list[tuple[list[str], str, str]] = [
    (["crude", "brent", "wti", "opec", "oil price"], "energy", "US_MACRO"),
    (["fed", "fomc", "powell", "rate cut", "rate hike"], "it", "US_MACRO"),
    (["nasdaq", "s&p", "dow ", "wall street"], "it", "US_MACRO"),
    (["hormuz", "red sea", "iran", "israel", "ukraine", "war", "missile", "houthi"], "energy", "GEO"),
    (["hormuz", "red sea", "iran", "israel", "war"], "aviation", "GEO"),
    (["defence", "defense", "drdo", "border"], "defence", "GEO"),
    (["rupee", "fii", "dii", "rbi"], "banking", "US_MACRO"),
    (["copper", "aluminium", "steel duty"], "metals", "SECTOR"),
    (["usfda", "fda", "drug approval"], "pharma", "SECTOR"),
    (["monsoon", "drought", "crop", "kharif", "rainfall"], "agri", "SECTOR"),
]

HEADLINE_DENY = [
    "ipl", "bollywood", "celebrity", "recipe", "horoscope",
]


@dataclass
class ScoreBreakdown:
    magnitude: float
    unusualness: float
    corroboration: float
    freshness: float
    total: float


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def z_score(values: list[float], latest: float) -> float:
    if len(values) < 5:
        return 0.0
    mu = statistics.mean(values)
    sd = statistics.pstdev(values) or 1e-9
    return (latest - mu) / sd


def freshness_weight(freshness: str | None) -> float:
    """Param 4 — DELAYED/CONFLICT down-weight before threshold comparison."""
    return FRESHNESS_SCORE_WEIGHT.get((freshness or "LIVE").upper(), 1.0)


def apply_freshness_to_score(raw: float, freshness: str | None) -> float:
    return clamp(raw * freshness_weight(freshness))


def sensitivity_threshold(base: float, sensitivity: str) -> float:
    """Param 1 — Low raises the bar; High lowers it."""
    mult = SENSITIVITY_THRESHOLD_MULT.get((sensitivity or "med").lower(), 1.0)
    return base * mult


# ---------------------------------------------------------------------------
# Param 6 — swappable scorer interface (rule-based is the only impl)
# ---------------------------------------------------------------------------


class Scorer(Protocol):
    def score(self, tick: dict, history: list[float]) -> float:
        """Return 0–100 significance for this tick given price history."""


class RuleBasedScorer:
    """
    Param 6 — only implementation. Swap via `active_scorer = …` without
    touching ingestion loop or digest routes.
    """

    def score(self, tick: dict, history: list[float]) -> float:
        """
        Param 1 significance core:
          raw ≈ |z| × volume_confirm  (folded to 0–100)
        Param 4: multiply by freshness_weight (DELAYED/CONFLICT → ×0.5) *before*
        the caller compares to threshold — bad data cannot mint false signals.
        """
        if len(history) < 8:
            return 0.0
        rets: list[float] = []
        for i in range(1, len(history)):
            prev, cur = history[i - 1], history[i]
            if prev > 0:
                rets.append((cur - prev) / prev * 100)
        if len(rets) < 5:
            return 0.0
        latest_ret = rets[-1]
        z = z_score(rets[:-1], latest_ret)
        vol_ratio = float(tick.get("volume") or 0) / max(float(tick.get("avg_volume") or 1), 1)
        if abs(z) < MICRO_Z_THRESHOLD or vol_ratio < VOLUME_CONFIRM_MIN:
            return 0.0
        sb = score_micro(z, vol_ratio)
        raw = sb.total
        # Corroboration model: price + volume (already) + headline → ×1.5
        if tick.get("has_headline") and vol_ratio >= VOLUME_CONFIRM_MIN:
            raw = clamp(raw * CORROBORATION_BOOST)
        return apply_freshness_to_score(raw, tick.get("freshness"))


# Single active implementation — ML scorer is the natural v2 swap target
active_scorer: Scorer = RuleBasedScorer()


def score_micro(z: float, volume_ratio: float) -> ScoreBreakdown:
    """
    Param 1 significance components for MICRO_SPIKE.
    Threshold to *emit*: |z| >= MICRO_Z_THRESHOLD (2.0) and vol_ratio >= 1.15
    — see module docstring for why 2.0.
    """
    vol_confirm = max(0.0, volume_ratio)
    mag = clamp(abs(z) * 12 * min(vol_confirm, 2.5) / 1.5)
    unusual = clamp(abs(z) * 10)
    corr = clamp((volume_ratio - 1.0) * 25)
    fresh = 10.0
    total = clamp(0.4 * mag + 0.3 * unusual + 0.2 * corr + 0.1 * fresh)
    return ScoreBreakdown(mag, unusual, corr, fresh, total)


def score_session(day_pct: float, atr_pct: float, residual_vs_nifty: float) -> ScoreBreakdown:
    mag = clamp(abs(day_pct) * 15)
    unusual = clamp((abs(day_pct) / max(atr_pct, 0.5)) * 25)
    corr = clamp(abs(residual_vs_nifty) * 12)
    fresh = 8.0
    total = clamp(0.4 * mag + 0.3 * unusual + 0.2 * corr + 0.1 * fresh)
    return ScoreBreakdown(mag, unusual, corr, fresh, total)


def score_gap(gap_pct: float) -> ScoreBreakdown:
    mag = clamp(abs(gap_pct) * 20)
    unusual = clamp(abs(gap_pct) * 18)
    corr = 10.0
    fresh = 10.0
    total = clamp(0.4 * mag + 0.3 * unusual + 0.2 * corr + 0.1 * fresh)
    return ScoreBreakdown(mag, unusual, corr, fresh, total)


def score_catalyst(kind: str, keyword_hits: int, has_price_move: bool) -> ScoreBreakdown:
    base = {"GEO": 70, "US_MACRO": 55, "SECTOR": 45}.get(kind, 40)
    mag = clamp(base * 0.6)
    unusual = clamp(keyword_hits * 15)
    corr = 40.0 if has_price_move else 12.0
    fresh = 10.0
    total = clamp(0.4 * mag + 0.3 * unusual + 0.2 * corr + 0.1 * fresh)
    return ScoreBreakdown(mag, unusual, corr, fresh, total)


def time_decay(hours_since_event: float, hours_away: float) -> float:
    """Param 1 — third factor of significance: score × time_decay for digest rank."""
    if hours_away <= 0:
        hours_away = 1.0
    relevance = 1.0 if hours_since_event <= hours_away + 0.5 else 0.55
    fade = math.exp(-hours_since_event / max(hours_away, 6.0))
    return relevance * (0.45 + 0.55 * fade)


def classify_quote_age(age_seconds: float, market_open: bool) -> DataFreshness:
    from app.config import settings

    if not market_open:
        return DataFreshness.CLOSED
    if age_seconds <= settings.live_max_age_s:
        return DataFreshness.LIVE
    if age_seconds <= settings.delayed_max_age_s:
        return DataFreshness.DELAYED
    return DataFreshness.STALE


def resolve_price_conflict(
    primary_px: float,
    primary_ts: float,
    secondary_px: float | None,
    secondary_ts: float | None,
) -> tuple[float, float, DataFreshness | None, float | None]:
    """
    Param 4: if two sources disagree beyond CONFLICT_TOLERANCE, keep the more
    recent price, return CONFLICT badge + logged relative delta.
    """
    if secondary_px is None or secondary_ts is None or primary_px <= 0:
        return primary_px, primary_ts, None, None
    delta = abs(primary_px - secondary_px) / primary_px
    if delta <= CONFLICT_TOLERANCE:
        if secondary_ts > primary_ts:
            return secondary_px, secondary_ts, None, None
        return primary_px, primary_ts, None, None
    if secondary_ts >= primary_ts:
        return secondary_px, secondary_ts, DataFreshness.CONFLICT, delta
    return primary_px, primary_ts, DataFreshness.CONFLICT, delta


def peer_relative_tag(symbol: str, move_pct: float, day_pct_by_symbol: dict[str, float]) -> str:
    """
    Param 2 — one flag: IDIOSYNCRATIC (stock alone) vs SECTOR (peers moved with it).
    Compare |stock move − sector median| in the same window.
    """
    sector = SYMBOL_TO_SECTOR.get(symbol)
    if not sector:
        return "IDIOSYNCRATIC"
    peers = [s for s in SECTOR_SYMBOLS.get(sector, []) if s != symbol]
    peer_moves = [day_pct_by_symbol[s] for s in peers if s in day_pct_by_symbol]
    if len(peer_moves) < 2:
        return "IDIOSYNCRATIC"
    med = statistics.median(peer_moves)
    # Same direction and stock within ~1pp of sector median → sector-wide
    same_dir = (move_pct >= 0) == (med >= 0)
    if same_dir and abs(med) >= 0.6 and abs(move_pct - med) <= 1.0:
        return "SECTOR"
    if abs(move_pct - med) <= 0.4 and abs(med) >= 0.5:
        return "SECTOR"
    return "IDIOSYNCRATIC"


def match_headline(text: str) -> list[tuple[str, str, list[str]]]:
    low = text.lower()
    if any(d in low for d in HEADLINE_DENY):
        return []
    out: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()
    for keys, sector, kind in KEYWORD_SECTOR:
        if any(k in low for k in keys):
            if sector in seen:
                continue
            seen.add(sector)
            out.append((sector, kind, SECTOR_SYMBOLS.get(sector, [])))
    return out


def digest_reason(event_type: EventType, symbol: str, payload: dict) -> str:
    """One-line reason only (Param 2)."""
    if payload.get("corroborated"):
        return "price+vol+headline corroborated ×1.5"
    if event_type == EventType.MICRO_SPIKE:
        base = (
            f"z={payload.get('z', 0):.1f} · vol×{payload.get('vol_ratio', 1):.1f}"
            + (" · no wire" if not payload.get("has_headline") else " · wire ok")
        )
        n = payload.get("count", 1)
        return f"{base} · ×{n}" if n and n > 1 else base
    if event_type == EventType.SESSION_MOVE:
        return f"day {payload.get('day_pct', 0):+.2f}% vs ATR {payload.get('atr_pct', 0):.1f}%"
    if event_type == EventType.OPEN_GAP:
        return f"gap {payload.get('gap_pct', 0):+.2f}% vs prev close"
    if event_type == EventType.CATALYST:
        return (payload.get("headline") or payload.get("kind", "news"))[:100]
    if event_type == EventType.LAG_ALERT:
        return payload.get("note") or payload.get("headline", "disruption ahead of price")[:100]
    return "No unread scores above floor"


def digest_magnitude(event_type: EventType, payload: dict, score: float) -> str:
    if event_type == EventType.MICRO_SPIKE:
        return f"{payload.get('move_pct', 0):+.2f}%"
    if event_type == EventType.SESSION_MOVE:
        return f"{payload.get('day_pct', 0):+.2f}%"
    if event_type == EventType.OPEN_GAP:
        return f"{payload.get('gap_pct', 0):+.2f}%"
    if event_type == EventType.LAG_ALERT:
        return f"sev {payload.get('severity', 0):.2f}"
    return f"{score:.0f}"
