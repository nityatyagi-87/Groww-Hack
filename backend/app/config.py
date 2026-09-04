from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/watchlist.db"
    price_poll_seconds: float = 8.0  # legacy; tiered hot/cold used instead
    # Param 5 — hot/cold data tiering by watcher count
    hot_poll_seconds: float = 5.0
    cold_poll_seconds: float = 20.0
    headline_poll_seconds: float = 90.0
    digest_limit: int = 15
    micro_z_threshold: float = 2.0
    session_move_pct: float = 2.0
    gap_pct: float = 1.5
    tick_window: int = 30
    demo_mode: bool = True
    max_watchlist: int = 50
    live_max_age_s: float = 15.0
    delayed_max_age_s: float = 120.0


settings = Settings()
