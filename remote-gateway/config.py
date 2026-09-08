from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LINKEDIN_GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=10000, ge=1, le=65535)

    public_base_url: str = "http://127.0.0.1:10000"
    mcp_path: str = "/mcp"

    # Retained for compatibility. New requests are routed through RuntimeManager.
    mcp_upstream_url: str = "http://127.0.0.1:8000/mcp"

    # OAuth.
    oauth_issuer: str = "http://127.0.0.1:10000"
    oauth_audience: str = "linkedin-mcp"
    oauth_signing_secret: str = "CHANGE-ME"

    admin_email: str = ""

    # Persistent gateway data.
    data_dir: str = "./data"

    # Account runtime allocation.
    runtime_base_port: int = Field(
        default=11000,
        ge=1024,
        le=65000,
    )
    runtime_start_timeout_seconds: float = Field(
        default=30.0,
        ge=5,
        le=300,
    )

    @property
    def production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
