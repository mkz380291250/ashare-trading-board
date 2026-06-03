from app.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h:5432/db")
    monkeypatch.setenv("TUSHARE_TOKEN", "tok")
    monkeypatch.setenv("INITIAL_CASH", "500000")
    s = Settings()
    assert s.database_url.startswith("postgresql")
    assert s.tushare_token == "tok"
    assert s.initial_cash == 500000
    assert s.deepseek_model == "deepseek-v4-pro"  # default


def test_decision_llm_defaults():
    s = Settings()
    assert s.decision_llm == "local"
    assert s.claude_bin.endswith("claude")


def test_research_config_defaults():
    from app.config import Settings
    s = Settings()
    assert s.research_llm == "local"
    assert s.research_max_per_min == 50
