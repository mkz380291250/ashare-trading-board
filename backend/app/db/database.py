from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()


def make_engine(url: str | None = None):
    settings = get_settings()
    u = url or settings.database_url
    # sqlite + threaded server (uvicorn/TestClient) needs check_same_thread=False
    connect_args = {"check_same_thread": False} if u.startswith("sqlite") else {}
    return create_engine(u, future=True, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
