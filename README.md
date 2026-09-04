# SignalList

**Digest-first Indian market watchlist** — not a price grid.

Pitch headline: **event taxonomy is meaningful change** —
`MICRO_SPIKE` · `SESSION_MOVE` · `OPEN_GAP` · `CATALYST` · `LAG_ALERT` · `QUIET`.

> Open → see unread meaningful changes → then go live.

---

## Persistence (Param 3)

`event_reads(user_id, event_id, read_at)` is per-user, server-side, durable SQL (Postgres contract; SQLite in this demo). Digest = unread events for the watchlist; `POST /digest/ack` marks specific `event_ids` read — never on page load. Partial reads survive tab close.

---

## Scale (Param 5)

Ingestion runs once per distinct symbol (union across watchlists) with Redis-shaped fan-out (`LiveBus`). **Hot/cold tiering:** top-decile symbols by watcher-count poll every 5s; the rest every 20s. Same-type events within 5 minutes collapse to one card with a count.

---

## Kept simple (Param 6)

Rule-based scoring (not ML), one weather/crop alt overlay, and a JWT stub for auth. Scorer is pluggable by design (`Scorer.score(tick, history) → float`); rule-based now, ML-based is the natural v2 without touching ingestion or digest logic.

---

## Conflict / freshness (Param 4)

Quotes carry `LIVE` / `DELAYED` / `STALE` / `CONFLICT`. Disagreeing sources beyond 15 bps → keep newer, badge **CONFLICT**. DELAYED/CONFLICT also **down-weight score ×0.5 before threshold** so bad data cannot mint false “meaningful” events.

---

## Significance (Param 1)

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

## Demo script (2 min)

1. Sensitivity Low/Med/High → floor changes.  
2. Digest cards: peer **SECTOR** vs **IDIOSYNCRATIC**; ×N de-dup counts.  
3. Mark unread seen (per-event ack); reopen — read items stay gone.  
4. CONFLICT / DELAYED ticks score quieter.  
5. Weather/crop view; US indexes → chart.  
6. **decisions** → `GET /api/policy`.

---

## API

- `POST /api/auth/login`  
- `GET /api/digest` · `POST /api/digest/ack` `{event_ids}`  
- `GET|PUT /api/sensitivity`  
- `GET|POST /api/watchlist` · `DELETE /api/watchlist/{symbol}`  
- `GET /api/chart/{symbol}` · `GET /api/alt/factors` · `GET /api/alt/us-indexes`  
- `WS /ws/live?user=…`

---

## How this maps to the judging criteria

1. **Meaningful change** — taxonomy + `|z|×vol×decay` (`MICRO_Z_THRESHOLD=2.0`); **+ sensitivity Low/Med/High × threshold; corroboration model price+vol+headline → one card ×1.5**.  
2. **What to surface** — digest card fields in `routes/digest.py`; **+ peer flag IDIOSYNCRATIC vs SECTOR (vs sector median)**.  
3. **Persistence** — **+ `event_reads` per-event ack; digest = unread watchlist events** (not a single `last_seen` cutoff).  
4. **Stale/delayed/conflict** — LIVE/DELAYED/STALE/CONFLICT badges; **+ DELAYED/CONFLICT score ×0.5 before threshold** (ties to Param 1).  
5. **Scale** — distinct-symbol union + LiveBus; **+ hot/cold polling (top-decile 5s / rest 20s) + 5m event de-dup with count**.  
6. **Simple vs complex** — rule scoring, one overlay, JWT stub; **+ pluggable `Scorer` interface (`RuleBasedScorer` only; ML = v2 without touching ingest/digest)**.
