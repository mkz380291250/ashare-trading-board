from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()


def make_engine(url: str | None = None):
    settings = get_settings()
    u = url or settings.database_url
    is_sqlite = u.startswith("sqlite")
    # sqlite + threaded server (uvicorn/TestClient) needs check_same_thread=False;
    # timeout=30s 让写操作在库被占用时排队而非立刻 "database is locked"。
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    engine = create_engine(u, future=True, connect_args=connect_args)
    if is_sqlite:
        # 多进程并发写 ashare.db(日更/分钟更新/后端)必须 WAL:读写不互斥、
        # 单写多读,几乎消除 "database is locked"。WAL 是库级持久属性;busy_timeout
        # 兜底再等 30s。:memory: 库设 WAL 会返回 "memory",无害。
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
