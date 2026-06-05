from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="A-Share Trading Board")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from app.api import (routes_account, routes_trade, routes_market,
                         routes_discovery, routes_decisions, routes_screener,
                         routes_research, routes_backtest, routes_tracklist,
                         routes_kline)
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)
    app.include_router(routes_discovery.router)
    app.include_router(routes_decisions.router)
    app.include_router(routes_screener.router)
    app.include_router(routes_research.router)
    app.include_router(routes_backtest.router)
    app.include_router(routes_tracklist.router)
    app.include_router(routes_kline.router)

    settings = get_settings()
    if settings.enable_scheduler:
        from app.scheduler import start_scheduler
        from scripts.daily_full import run_all
        app.state.scheduler = start_scheduler(
            run_all, hour=settings.daily_update_hour,
            minute=settings.daily_update_minute)

    return app


app = create_app()
