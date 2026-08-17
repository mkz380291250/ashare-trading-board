from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ashare:ashare@localhost:5432/ashare"
    tushare_token: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    qlib_data_dir: str = "./data/qlib_cn"
    discovery_universe: str = "cyb"        # 生产选股宇宙(2026-07-03 全市场→创业板,
                                           # 同窗回测年化28.9%→42.3%、回撤-32%→-26%);
                                           # 挖掘/冻结默认跟随此值,防 run_remine 静默切回
    discovery_horizon: int = 20            # 生产因子持有/预测周期(T+1买、T+1+h卖的h日)
                                           # 挖掘/冻结默认跟随此值,防脚本静默用旧的 h5
    initial_cash: int = 1_000_000
    decision_llm: str = "local"            # local | deepseek
    claude_bin: str = "/usr/local/bin/claude"
    debate_rounds: int = 2
    research_llm: str = "local"            # local | deepseek
    research_max_per_min: int = 50         # tushare 研报接口限流(保守)
    enable_scheduler: bool = False         # 默认关,生产/部署时置 True
    daily_update_hour: int = 16            # 北京时间 16:00
    daily_update_minute: int = 0
    target_positions: int = 15             # 组合目标持仓数(空位上界)
    quality_pctl: float = 0.30             # 买入候选须在全市场复合分前 30%
    min_confidence: float = 0.6            # BUY/SELL 自动执行的置信度门
    max_debate: int = 8                    # 单日辩论上限(防烧 LLM;本地 claude CLI 每只耗时较长,控制在8只内)
    buy_trend_window: int = 0              # 买入趋势闸:均线窗口(0=关闭)。默认关——
                                           # 当前 frozen 因子是 h20 低风险异象型(低波/低换手/低流动),
                                           # 开趋势闸=过滤掉因子全部选票→零买入。仅当换成
                                           # 趋势型因子时才设 20 开启。
    buy_trend_tol: float = 0.02            # 收盘可低于均线的容差(2% 内仍算不破位)
    policy_auto_remine: bool = True        # 因子衰减时自动重挖换产物
    ic_decay_window: int = 20              # 滚动 RankIC 窗口
    ic_decay_consecutive: int = 5          # 连续低于阈值天数
    ic_decay_threshold: float = 0.02       # 滚动 RankIC 阈值
    dd_stop: float = 0.20                  # 回撤停买阈值
    hitrate_stop: float = 0.40             # 胜率停买阈值
    weak_pctl: float = 0.50                # 持仓弱因子百分位门
    weak_consecutive: int = 3              # 弱因子连续天数


def get_settings() -> Settings:
    return Settings()


def resolve_horizon(cli_value, settings) -> int:
    """CLI 显式值优先,缺省(None)回落到 settings.discovery_horizon。"""
    return cli_value if cli_value is not None else settings.discovery_horizon
