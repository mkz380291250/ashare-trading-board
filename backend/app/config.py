from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ashare:ashare@localhost:5432/ashare"
    tushare_token: str = ""                # 2026-09-16 到期后弃用;行情改 baostock/腾讯
    quotes_source: str = "baostock"        # 日线"补缺天"时逐只 K 线的首选源:baostock | tencent。
                                           # 正常每晚走腾讯批量快照(28 个请求拿全市场,秒级),
                                           # 只有漏跑了一天才逐只补:baostock 字段全但同 IP 单会话、
                                           # 0.3~3s/只(2~4 小时),连续失败自动熔断切腾讯 K 线
                                           # (腾讯 K 线对 ~30 req/s 突发会 WAF 封 501,已限速 8/s)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    qlib_data_dir: str = "./data/qlib_cn"
    qlib_export_start: str = "2021-01-01"  # 每晚 qlib 重建的起始日;库里 2010 年起都有(2026-09-15
                                           # tushare 到期前追溯),但全导会让夜链重建慢 3 倍,
                                           # 做长周期回测/挖掘时再临时改早
    financials_weekday: int = 4            # 每周几(0=周一)用 baostock 季报续接财务(ts_income),
                                           # 夜链 financials 步;-1=关闭。tushare 到期后 sp_ttm 等因子靠它
    qlib_research_dir: str = "./data/qlib_cn_full"  # 研究库(2010 起 + PIT 财务/资金流字段),
                                           # 由 build_qlib_data.py --start 2010-01-01 --extra 手动重建,不进夜链
    discovery_universe: str = "cyb"        # 生产选股宇宙(2026-07-03 全市场→创业板,
                                           # 同窗回测年化28.9%→42.3%、回撤-32%→-26%);
                                           # 挖掘/冻结默认跟随此值,防 run_remine 静默切回
    discovery_horizon: int = 20            # 生产因子持有/预测周期(T+1买、T+1+h卖的h日)
                                           # 挖掘/冻结默认跟随此值,防脚本静默用旧的 h5
    initial_cash: int = 1_000_000
    decision_llm: str = "local"            # local | deepseek
    claude_bin: str = "/usr/local/bin/claude"
    claude_model: str = "claude-opus-5"  # 辩论本地 claude 模型(2026-09-14 → opus-5,用户指定;CLI实测可用)
    debate_rounds: int = 2
    research_llm: str = "local"            # local | deepseek
    research_max_per_min: int = 50         # tushare 研报接口限流(保守)
    enable_scheduler: bool = False         # 默认关,生产/部署时置 True
    daily_update_hour: int = 16            # 北京时间 16:00
    daily_update_minute: int = 0
    target_positions: int = 15             # 组合目标持仓数(空位上界)
    quality_pctl: float = 0.30             # 买入候选须在全市场复合分前 30%
    min_confidence: float = 0.6            # 置信度门(仅 UI 手动单票 run_one_decision 用;夜链已改系统化 TopkDropout,不再用它)
    max_debate: int = 8                    # 单日辩论上限(防烧 LLM;本地 claude CLI 每只耗时较长,控制在8只内)
    buy_trend_window: int = 0              # 买入趋势闸:均线窗口(0=关闭)。默认关——
                                           # 当前 frozen 因子是 h20 低风险异象型(低波/低换手/低流动),
                                           # 开趋势闸=过滤掉因子全部选票→零买入。仅当换成
                                           # 趋势型因子时才设 20 开启。
    buy_trend_tol: float = 0.02            # 收盘可低于均线的容差(2% 内仍算不破位)
    rebalance_weekday: int = 0             # 周度再平衡日(0=周一);其余交易日持有不动
    rebalance_buffer: int = 5             # TopkDropout 缓冲:持仓跌出 topk+buffer 名才卖
    rebalance_n_drop: int = 2             # 每周因排名换出上限(封顶换手);辩论扫雷不受此限
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
