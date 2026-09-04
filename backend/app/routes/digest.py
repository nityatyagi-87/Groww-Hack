from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.bus import bus
from app.config import settings
from app.db import (
    ensure_user,
    get_db,
    get_user_sensitivity,
    get_watchlist,
    mark_events_read,
    set_user_sensitivity,
    unread_events_for_symbols,
)
from app.scoring import (
    CORROBORATION_BOOST,
    DIGEST_SCORE_FLOOR,
    EventType,
    digest_magnitude,
    digest_reason,
    peer_relative_tag,
    sensitivity_threshold,
    time_decay,
)

router = APIRouter(prefix="/api", tags=["digest"])


class AckBody(BaseModel):
    """Param 3 — per-event ack (unread persist across partial sessions)."""
    event_ids: list[int] = Field(default_factory=list)


class SensitivityBody(BaseModel):
    sensitivity: str = Field(..., pattern="^(low|med|high)$")


def uid(x_user_id: Optional[str]) -> str:
    return (x_user_id or "demo").strip() or "demo"


def _move_pct(payload: dict, event_type: str) -> float:
    if event_type == "MICRO_SPIKE":
        return float(payload.get("move_pct") or 0)
    if event_type == "SESSION_MOVE":
        return float(payload.get("day_pct") or 0)
    if event_type == "OPEN_GAP":
        return float(payload.get("gap_pct") or 0)
    return float(payload.get("day_pct") or payload.get("move_pct") or 0)


def _collapse_corroborated(items: list[dict]) -> list[dict]:
    """
    Corroboration model (Param 1): when price+volume+headline all corroborate on
    one symbol, keep one higher-confidence card (×1.5) instead of listing separate
    MICRO/SESSION and CATALYST events.
    """
    by_sym: dict[str, list[dict]] = {}
    for it in items:
        by_sym.setdefault(it["symbol"], []).append(it)

    out: list[dict] = []
    for sym, group in by_sym.items():
        price_types = {"MICRO_SPIKE", "SESSION_MOVE", "OPEN_GAP"}
        price = [g for g in group if g["event_type"] in price_types]
        cats = [g for g in group if g["event_type"] == "CATALYST"]
        rest = [g for g in group if g["event_type"] not in price_types | {"CATALYST"}]

        if price and cats:
            primary = max(price, key=lambda x: x["rank"])
            primary = {**primary}
            primary["score"] = min(100.0, primary.get("score", primary["rank"]) * CORROBORATION_BOOST)
            primary["rank"] = round(primary["rank"] * CORROBORATION_BOOST, 1)
            primary["reason"] = "price+vol+headline corroborated ×1.5"
            # Drop separate catalysts for this symbol; keep other price cards only if distinct
            out.append(primary)
            for p in price:
                if p["id"] != primary["id"]:
                    out.append(p)
            out.extend(rest)
        else:
            out.extend(group)
    return out


@router.get("/digest")
async def get_digest(x_user_id: Optional[str] = Header(default="demo")):
    """
    Param 3: Digest = unread events for the user's watchlist (event_reads),
    not a single last_seen timestamp cutoff.
    """
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    sensitivity = await get_user_sensitivity(db, user_id)
    symbols = await get_watchlist(db, user_id)
    now = time.time()

    # away_hours: age of oldest unread, else quiet window
    raw = await unread_events_for_symbols(db, user_id, symbols, settings.digest_limit)
    if raw:
        oldest = min(e["ts"] for e in raw)
        away_h = max((now - oldest) / 3600.0, 0.25)
    else:
        away_h = 24.0

    floor = sensitivity_threshold(DIGEST_SCORE_FLOOR, sensitivity)
    day_map = {s: float(q.get("day_pct") or 0) for s, q in bus.latest.items()}

    ranked = []
    for e in raw:
        # Param 1 — sensitivity multiplies significance threshold
        if e["score"] < floor:
            continue
        age_h = (now - e["ts"]) / 3600.0
        rank = e["score"] * time_decay(age_h, away_h)
        et = EventType(e["event_type"])
        move = _move_pct(e["payload"], e["event_type"])
        peer = peer_relative_tag(e["symbol"], move, day_map)
        count = int(e["payload"].get("count") or 1)
        ranked.append(
            {
                "id": e["id"],
                "symbol": e["symbol"],
                "event_type": e["event_type"],
                "magnitude": digest_magnitude(et, e["payload"], e["score"]),
                "reason": digest_reason(et, e["symbol"], e["payload"]),
                "ts": e["ts"],
                "freshness": e["payload"].get("freshness", "LIVE"),
                "peer": peer,  # Param 2 — IDIOSYNCRATIC | SECTOR
                "count": count,  # Param 5 — de-dup collapse count
                "rank": round(rank, 1),
                "score": e["score"],
            }
        )

    ranked = _collapse_corroborated(ranked)
    ranked.sort(key=lambda x: x["rank"], reverse=True)
    ranked = ranked[: settings.digest_limit]
    # Strip internal score from card payload surface (keep peer/count)
    for r in ranked:
        r.pop("score", None)

    await db.close()

    quiet = len(ranked) == 0
    return {
        "user_id": user_id,
        "sensitivity": sensitivity,
        "threshold_floor": round(floor, 1),
        "away_hours": round(away_h, 2),
        "taxonomy": [t.value for t in EventType],
        "corroboration_model": "price+volume+headline → one card ×1.5",
        "items": ranked,
        "quiet": quiet,
        "quiet_card": {
            "symbol": "—",
            "event_type": "QUIET",
            "magnitude": "—",
            "reason": f"No unread scores above floor ({floor:.0f}) for sensitivity={sensitivity}",
            "ts": now,
            "freshness": "LIVE",
            "peer": "IDIOSYNCRATIC",
            "count": 1,
        }
        if quiet
        else None,
    }


@router.post("/digest/ack")
async def ack_digest(body: AckBody, x_user_id: Optional[str] = Header(default="demo")):
    """Param 3 — mark specific event_ids read; unread persist if tab closed mid-digest."""
    user_id = uid(x_user_id)
    if not body.event_ids:
        raise HTTPException(400, "event_ids required")
    db = await get_db()
    await ensure_user(db, user_id)
    n = await mark_events_read(db, user_id, body.event_ids)
    await db.close()
    return {"ok": True, "marked": n}


@router.get("/sensitivity")
async def get_sensitivity(x_user_id: Optional[str] = Header(default="demo")):
    user_id = uid(x_user_id)
    db = await get_db()
    await ensure_user(db, user_id)
    level = await get_user_sensitivity(db, user_id)
    await db.close()
    return {
        "sensitivity": level,
        "threshold_mult": {"low": 1.35, "med": 1.0, "high": 0.7}[level],
    }


@router.put("/sensitivity")
async def put_sensitivity(
    body: SensitivityBody, x_user_id: Optional[str] = Header(default="demo")
):
    user_id = uid(x_user_id)
    db = await get_db()
    level = await set_user_sensitivity(db, user_id, body.sensitivity)
    await db.close()
    return {"sensitivity": level}
