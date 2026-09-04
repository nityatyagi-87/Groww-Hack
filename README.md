# SignalList

**Digest-first Indian market watchlist** 

**Event taxonomy is meaningful change** —
`MICRO_SPIKE` · `SESSION_MOVE` · `OPEN_GAP` · `CATALYST` · `LAG_ALERT` · `QUIET`.

> Open → see unread meaningful changes → then go live.

---

## Persistence 

`event_reads(user_id, event_id, read_at)` is per-user, server-side, durable SQL (Postgres contract; SQLite in this demo). Digest = unread events for the watchlist; `POST /digest/ack` marks specific `event_ids` read — never on page load. Partial reads survive tab close.

---

## Scale 

Ingestion runs once per distinct symbol (union across watchlists) with Redis-shaped fan-out (`LiveBus`). **Hot/cold tiering:** top-decile symbols by watcher-count poll every 5s; the rest every 20s. Same-type events within 5 minutes collapse to one card with a count.

---

## Kept simple 

Rule-based scoring (not ML), one weather/crop alt overlay, and a JWT stub for auth. Scorer is pluggable by design (`Scorer.score(tick, history) → float`); rule-based now, ML-based is the natural v2 without touching ingestion or digest logic.

---

## Conflict / freshness 

Quotes carry `LIVE` / `DELAYED` / `STALE` / `CONFLICT`. Disagreeing sources beyond 15 bps → keep newer, badge **CONFLICT**. DELAYED/CONFLICT also **down-weight score ×0.5 before threshold** so bad data cannot mint false “meaningful” events.

---

## Significance 

Documented in `RuleBasedScorer.score`: `|z| × volume_confirm × time_decay`, emit when `|z| ≥ MICRO_Z_THRESHOLD` (2.0) and `vol_ratio ≥ 1.15`. Per-user **sensitivity** (low/med/high) multiplies the digest threshold. **Corroboration model:** price+volume+headline → one card ×1.5 (not three separate events).

---

## Run

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — login with any email/password.

---



## API

- `POST /api/auth/login`  
- `GET /api/digest` · `POST /api/digest/ack` `{event_ids}`  
- `GET|PUT /api/sensitivity`  
- `GET|POST /api/watchlist` · `DELETE /api/watchlist/{symbol}`  
- `GET /api/chart/{symbol}` · `GET /api/alt/factors` · `GET /api/alt/us-indexes`  
- `WS /ws/live?user=…`

---

