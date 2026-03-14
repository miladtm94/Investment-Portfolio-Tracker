from pydantic_settings import BaseSettings
from pydantic import SecretStr
from functools import lru_cache


class Settings(BaseSettings):
    # ─── App ─────────────────────────────────────────────────────────────
    app_name: str = "Investment Intelligence Platform"
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # ─── Australian localisation ──────────────────────────────────────────
    default_currency: str = "AUD"
    default_timezone: str = "Australia/Sydney"
    default_tax_jurisdiction: str = "AU"
    # Individual CGT discount rate (50% for individuals, 33.33% for SMSF)
    cgt_discount_rate: float = 0.50
    # ATO tax year starts July 1
    tax_year_start_month: int = 7
    tax_year_start_day: int = 1
    # RBA exchange rate API
    rba_fx_api_url: str = "https://www.rba.gov.au/statistics/tables/xls/f11.1-data.xlsx"

    # ─── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://invest:investpass@localhost:5432/investment_platform"

    # ─── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    cache_ttl_seconds: int = 300  # 5 minutes default

    # ─── Security ─────────────────────────────────────────────────────────
    jwt_secret_key: SecretStr = SecretStr("dev-secret-change-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 24  # 24 hours
    encryption_key: SecretStr = SecretStr("dev-encryption-key-32bytes-here!")

    # ─── AI ───────────────────────────────────────────────────────────────
    anthropic_api_key: SecretStr = SecretStr("")
    claude_model: str = "claude-opus-4-6"
    claude_max_tokens: int = 4096

    # ─── Market Data ──────────────────────────────────────────────────────
    polygon_api_key: SecretStr = SecretStr("")
    coingecko_api_key: SecretStr = SecretStr("")
    alpha_vantage_api_key: SecretStr = SecretStr("")

    # ─── Broker Integration ───────────────────────────────────────────────
    plaid_client_id: SecretStr = SecretStr("")
    plaid_secret: SecretStr = SecretStr("")
    plaid_env: str = "sandbox"

    snaptrade_client_id: SecretStr = SecretStr("")
    snaptrade_consumer_key: SecretStr = SecretStr("")

    # ─── Crypto Exchanges ─────────────────────────────────────────────────
    kraken_api_key: SecretStr = SecretStr("")
    kraken_api_secret: SecretStr = SecretStr("")
    coinbase_api_key: SecretStr = SecretStr("")
    coinbase_api_secret: SecretStr = SecretStr("")
    binance_api_key: SecretStr = SecretStr("")
    binance_api_secret: SecretStr = SecretStr("")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
