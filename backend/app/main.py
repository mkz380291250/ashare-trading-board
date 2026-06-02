from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="A-Share Trading Board")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from app.api import routes_account, routes_trade, routes_market
    app.include_router(routes_account.router)
    app.include_router(routes_trade.router)
    app.include_router(routes_market.router)

    return app


app = create_app()
