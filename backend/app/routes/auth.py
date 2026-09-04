"""Auth only — JWT-stub session tokens keyed to server user_id (Param 3/6)."""
from __future__ import annotations

import hashlib
import time

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.db import ensure_user, get_db
from app.seed import DEFAULT_WATCHLIST

router = APIRouter(prefix="/api/auth", tags=["auth"])
_SESSIONS: dict[str, str] = {}


class LoginBody(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)
    name: str | None = None


@router.post("/login")
async def login(body: LoginBody):
    email = body.email.strip().lower()
    user_id = hashlib.sha256(email.encode()).hexdigest()[:12]
    db = await get_db()
    await ensure_user(db, user_id)
    cur = await db.execute(
        "SELECT COUNT(*) AS c FROM watchlist_items WHERE user_id=?", (user_id,)
    )
    row = await cur.fetchone()
    if row and row["c"] == 0:
        now = time.time()
        for i, sym in enumerate(DEFAULT_WATCHLIST):
            await db.execute(
                "INSERT OR IGNORE INTO watchlist_items(user_id,symbol,added_at) VALUES(?,?,?)",
                (user_id, sym, now + i),
            )
        await db.commit()
    await db.close()
    token = hashlib.sha256(f"{user_id}:{time.time()}:{body.password}".encode()).hexdigest()[:32]
    _SESSIONS[token] = user_id
    return {
        "token": token,
        "user_id": user_id,
        "name": body.name or email.split("@")[0],
        "email": email,
    }


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        _SESSIONS.pop(authorization[7:], None)
    return {"ok": True}
