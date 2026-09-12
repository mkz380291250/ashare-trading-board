from app.config import Settings


def test_phase2_defaults():
    s = Settings()
    assert s.target_positions == 15
    assert s.quality_pctl == 0.30
    assert s.min_confidence == 0.6
    assert s.max_debate == 8


def test_claude_model_default_opus():
    # 辩论本地 claude 模型(2026-09-12 升级 opus-4-8);_llm 会把它传给 LocalClaudeClient
    assert Settings().claude_model == "claude-opus-4-8"


def test_llm_builds_local_claude_with_configured_model():
    import scripts.daily_full as df
    from app.decision.llm import LocalClaudeClient
    client = df._llm(Settings())
    assert isinstance(client, LocalClaudeClient)
    assert client.model == "claude-opus-4-8"


def test_discovery_universe_default_cyb():
    # 生产选股宇宙单一来源(2026-07-03 切创业板);挖掘/冻结默认跟随,防 run_remine 静默切回全市场
    assert Settings().discovery_universe == "cyb"


def test_discovery_horizon_default_20():
    from app.config import Settings
    assert Settings().discovery_horizon == 20


def test_resolve_horizon_prefers_cli_then_settings():
    from app.config import Settings, resolve_horizon
    s = Settings()
    assert resolve_horizon(5, s) == 5          # 显式 CLI 值优先
    assert resolve_horizon(None, s) == 20      # 缺省回落到 settings


def test_rebalance_settings_defaults():
    from app.config import Settings
    s = Settings()
    assert s.rebalance_weekday == 0        # 周一
    assert s.rebalance_buffer == 5


def test_rebalance_n_drop_default_2():
    from app.config import Settings
    assert Settings().rebalance_n_drop == 2
