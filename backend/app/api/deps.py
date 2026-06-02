from app.db.database import make_engine, make_session_factory

_engine = None
_factory = None


def get_session():
    global _engine, _factory
    if _factory is None:
        _engine = make_engine()
        _factory = make_session_factory(_engine)
    s = _factory()
    try:
        yield s
    finally:
        s.close()
