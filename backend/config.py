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

    # OpenAI
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o"

    # Google Gemini
    gemini_api_key: SecretStr = SecretStr("")
    # gemini_model = synthesis-quality model used when Gemini is the chosen provider
    gemini_model: str = "gemma-4-31b-it"

    # ─── Multi-agent models (Phase 3) ────────────────────────────────────
    # Specialist agents: Gemma 4 MoE (26B total / 4B active) — fast and free
    agent_model_cheap: str = "gemma-4-26b-a4b-it"
    # Synthesis agent uses best model: Claude Opus (claude provider) or gemini_model (gemini provider)
    agent_model_synthesis: str = "claude-opus-4-6"

    # ─── Local Ollama ─────────────────────────────────────────────────────
    # Ollama runs on the host machine; Docker services use host.docker.internal
    ollama_host: str = "http://host.docker.internal:11434"
    ollama_model: str = "gemma3:4b"            # pulled model name
    ollama_model_cheap: str = "gemma3:4b"      # for specialist agents
    # Fallback model if the primary isn't pulled yet
    ollama_model_fallback: str = "llama3.2:latest"

    # ─── LM Studio (local) ────────────────────────────────────────────────
    # LM Studio runs on the host with an OpenAI-compatible server
    # Enable: LM Studio → Local Server tab → Start Server, then load any model
    lmstudio_host: str = "http://host.docker.internal:1234"
    lmstudio_model: str = ""   # empty = auto-detect first loaded model

    # ─── Market Data ──────────────────────────────────────────────────────
    polygon_api_key: SecretStr = SecretStr("")
    coingecko_api_key: SecretStr = SecretStr("")
    alpha_vantage_api_key: SecretStr = SecretStr("")
    newsapi_key: SecretStr = SecretStr("")        # newsapi.org — for equity news

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
