"""Validated environment configuration.

Field names map case-insensitively onto the variables documented in
``.env.example``; that file is the single source of truth for what the judges
must set. Values are never logged — only the fact that a value is present.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- primary model -------------------------------------------------------
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"

    # --- fallback model ------------------------------------------------------
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""

    # --- CLAMP knobs ---------------------------------------------------------
    llm_samples: int = Field(default=5, ge=1, le=16)
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=8.0, gt=0)
    llm_max_attempts: int = Field(default=2, ge=1, le=4)
    llm_max_completion_tokens: int = Field(default=700, ge=200, le=4096)
    request_deadline_seconds: float = Field(default=27.0, gt=0)
    hedge_alpha: float = Field(default=0.10, ge=0.0, le=1.0)
    hedge_max_candidates: int = Field(default=5, ge=1, le=8)
    hedge_enabled: bool = True

    # --- service -------------------------------------------------------------
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    @property
    def has_primary(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url)

    @property
    def has_fallback(self) -> bool:
        return bool(self.llm_fallback_base_url and self.llm_fallback_model)

    @model_validator(mode="after")
    def require_some_language_model(self) -> Settings:
        """Fail fast at startup rather than at the judge's first request.

        A deployment with no reachable model cannot satisfy the mandatory
        LLM-interpretation requirement, and silently degrading every note to
        ``no_op`` would be worse than refusing to boot.
        """
        if not self.has_primary and not self.has_fallback:
            raise ValueError(
                "no language model configured: set LLM_API_KEY (with LLM_BASE_URL) "
                "or configure LLM_FALLBACK_BASE_URL and LLM_FALLBACK_MODEL"
            )
        return self

    def describe(self) -> dict[str, object]:
        """Startup banner. Reports presence of credentials, never their values."""
        return {
            "primary_model": self.llm_model if self.has_primary else None,
            "primary_key_present": bool(self.llm_api_key),
            "fallback_model": self.llm_fallback_model if self.has_fallback else None,
            "samples": self.llm_samples,
            "hedge_enabled": self.hedge_enabled,
            "request_deadline_seconds": self.request_deadline_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
