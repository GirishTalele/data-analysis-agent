from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/agent.db")
    log_level: str = Field(default="INFO")

    # LLM provider — auto-detected from whichever key is set if left blank
    llm_provider: str = Field(default="")   # "anthropic" | "gemini"
    llm_model: str = Field(default="")      # uses provider default when blank

    # Provider keys — set exactly one
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # --- Data-analysis-agent settings (spec/architecture.md -> New Settings) ---
    data_dir: str = Field(default="./data")
    max_upload_mb: int = Field(default=100)
    sandbox_timeout_seconds: int = Field(default=20)
    max_summary_rows: int = Field(default=20)
    max_summary_items: int = Field(default=50)
    max_steps: int = Field(default=5)
    gemini_input_price_per_1m: float = Field(default=1.25)
    gemini_output_price_per_1m: float = Field(default=5.00)
    # NOTE: attribute name already starts with "agent_" so env_prefix would otherwise
    # double up to AGENT_AGENT_HISTORY_TURNS — pin the alias explicitly.
    agent_history_turns: int = Field(default=10, validation_alias="AGENT_HISTORY_TURNS")

    # LangSmith tracing — these are bare env vars (no AGENT_ prefix) per LangSmith's
    # convention, so we override env_prefix per-field via validation_alias.
    langchain_tracing_v2: bool = Field(default=False, validation_alias="LANGCHAIN_TRACING_V2")
    langchain_api_key: str = Field(default="", validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field(default="", validation_alias="LANGCHAIN_PROJECT")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
