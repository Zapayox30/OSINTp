"""Application settings loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised, validated configuration.

    Values are read from environment variables (case-insensitive) or a local
    ``.env`` file. Unknown variables are ignored so the same env file can be
    shared with other tooling.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application metadata
    app_name: str = "OSINTp"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    # HTTP client tuning
    http_timeout: float = 10.0
    http_max_connections: int = 50
    user_agent: str = "OSINTp/0.1 (+https://github.com/zapayox30/osintp)"

    # Maximum number of concurrent outbound probes per request
    max_concurrency: int = 20

    # CORS — comma separated origins or "*"
    cors_origins: str = "*"

    # Optional third-party API keys (modules degrade gracefully when unset)
    ipinfo_token: str | None = None
    hibp_api_key: str | None = None
    shodan_api_key: str | None = None

    # Persistence (SQLite) for cases / dossiers
    database_path: str = "data/osintp.db"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse the comma-separated ``cors_origins`` string into a list."""
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
