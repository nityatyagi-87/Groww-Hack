from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, chart, digest, live, watchlist
from app.seed import seed
from app.workers.alt import AltWorker
from app.workers.headlines import HeadlineWorker
from app.workers.price import PriceWorker

price_worker = PriceWorker()
headline_worker = HeadlineWorker()
alt_worker = AltWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed()
    price_worker.start()
    headline_worker.start()
    alt_worker.start()
    yield


app = FastAPI(title="SignalList", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(digest.router)
app.include_router(watchlist.router)
app.include_router(live.router)
app.include_router(chart.router)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "product": "SignalList",
        "pitch": "digest-first watchlist — event taxonomy is the product",
    }
