"""Application configuration loaded from environment variables / ``.env``.

Settings are resolved once, at import time, by :class:`clusterops_settings`.
All consumers (FastAPI, Alembic ``env.py``, pipelines, tests) share this single
object so that configuration can never drift between train and serve paths.

Synthetic data only — this project demonstrates AIOps engineering on generated
data; it contains no real pharmacy, order, or commercial data.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `backend/app/config.py` -> `backend/app` -> `backend` -> repository root
BACKEND_DIR: Path = Path(__file__).resolve().parents[1]
REPO_ROOT: Path = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Typed application settings.

    Values are read from the process environment first and from ``<repo>/.env``
    as a fallback. Field names map to upper-case environment variables
    (case-insensitive), e.g. ``DATABASE_URL`` -> :attr:`database_url`.
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://cluster:cluster@localhost:5432/clusterops",
        description="Async SQLAlchemy URL (asyncpg driver) used by the application.",
    )
    sync_database_url: str = Field(
        default="postgresql://cluster:cluster@localhost:5432/clusterops",
        description="Sync URL (psycopg2) required by Alembic and the test bootstrap.",
    )
    test_database_url: str = Field(
        default="postgresql+asyncpg://cluster:cluster@localhost:5432/clusterops_test",
        description="Async URL pointing at the disposable test database.",
    )
    test_sync_database_url: str = Field(
        default="postgresql://cluster:cluster@localhost:5432/clusterops_test",
        description="Sync URL pointing at the disposable test database.",
    )
    db_echo: bool = Field(default=False, description="Log every emitted SQL statement.")
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)

    # --- Experiment tracking ---------------------------------------------
    mlflow_tracking_uri: str = Field(default="http://localhost:5000")
    mlflow_experiment_name: str = Field(default="clusterops-demand-forecast")
    mlflow_model_name: str = Field(default="lgbm-demand-forecast")
    mlflow_tracking_username: str | None = Field(default=None)
    mlflow_tracking_password: str | None = Field(default=None)

    # --- Third party ------------------------------------------------------
    gemini_api_key: str | None = Field(
        default=None, description="Free-tier Gemini key; only used to re-rank ambiguous tokens."
    )
    gemini_model: str = Field(default="gemini-2.0-flash")

    # --- Orchestration ----------------------------------------------------
    prefect_api_url: str = Field(default="http://localhost:4200/api")

    # --- Application ------------------------------------------------------
    api_v1_prefix: str = Field(default="/api/v1")
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True, description="Emit structured JSON logs.")
    app_name: str = Field(default="ClusterOps API")
    app_version: str = Field(default="1.0.0")
    environment: str = Field(default="local", description="Deployment environment label used in logs.")

    # --- ML / safety thresholds ------------------------------------------
    confidence_threshold: float = Field(
        default=0.70, ge=0.0, le=1.0, description="rapidfuzz acceptance threshold."
    )
    review_confidence_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Below this confidence an order item is queued for human review.",
    )
    drift_psi_warning: float = Field(default=0.10, ge=0.0)
    drift_psi_alert: float = Field(default=0.20, ge=0.0)
    promotion_gate_improvement: float = Field(
        default=0.03, ge=0.0, description="Challenger must beat production MAE by 3% to be promoted."
    )

    # --- Synthetic data generator ----------------------------------------
    data_random_seed: int = Field(default=42)
    data_generation_days: int = Field(default=180, ge=1)

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: str) -> str:
        """Guard against a sync URL silently producing a blocking engine."""
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver: postgresql+asyncpg://<user>:<pw>@<host>:<port>/<db>"
            )
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Unsupported LOG_LEVEL: {value!r}")
        return level

    @property
    def mlflow_tracking_credentials(self) -> tuple[str, str] | None:
        """Basic-auth pair for MLflow, when configured."""
        if self.mlflow_tracking_username and self.mlflow_tracking_password:
            return (self.mlflow_tracking_username, self.mlflow_tracking_password)
        return None


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance.

    Cached so that the `.env` file is parsed exactly once per process; tests
    that need alternative values override the relevant environment variables
    *before* importing the application, or call ``get_settings.cache_clear()``.
    """
    return Settings()


settings: Settings = get_settings()

__all__ = ["BACKEND_DIR", "REPO_ROOT", "Settings", "get_settings", "settings"]