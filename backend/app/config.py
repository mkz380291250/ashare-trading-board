from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ashare:ashare@localhost:5432/ashare"
    tushare_token: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    qlib_data_dir: str = "./data/qlib_cn"
    initial_cash: int = 1_000_000
    decision_llm: str = "local"            # local | deepseek
    claude_bin: str = "/usr/local/bin/claude"
    debate_rounds: int = 2
    research_llm: str = "local"            # local | deepseek
    research_max_per_min: int = 50         # tushare 研报接口限流(保守)
    enable_scheduler: bool = False         # 默认关,生产/部署时置 True
    daily_update_hour: int = 16            # 北京时间 16:00
    daily_update_minute: int = 0


def get_settings() -> Settings:
    return Settings()
