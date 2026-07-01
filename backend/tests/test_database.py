from app.db.database import make_engine


def test_sqlite_engine_enables_wal_and_busy_timeout(tmp_path):
    """并发写 ashare.db(日更/分钟更新/后端)会撞 'database is locked';
    WAL + 大 busy_timeout 根治。"""
    db = tmp_path / "t.db"
    eng = make_engine(f"sqlite:///{db}")
    with eng.connect() as c:
        jm = c.exec_driver_sql("PRAGMA journal_mode").scalar()
        bt = c.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert jm.lower() == "wal"
    assert bt >= 30000


def test_memory_engine_still_usable(tmp_path):
    """内存库(测试用)设 WAL 无意义但不应报错。"""
    eng = make_engine("sqlite:///:memory:")
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT 1").scalar() == 1
