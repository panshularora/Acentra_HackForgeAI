"""Runtime configuration, read once from environment variables (or a .env file).

Every tunable number in the service lives here so the detector, the tailer and
the AWS publisher never carry their own magic constants.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ClaimsWatch"

    # Ingest
    log_path: Path = Path("logs/app.log")
    db_path: Path = Path("claimswatch.db")
    tail_poll_seconds: float = Field(default=0.25, gt=0)
    # Like `tail -f`, start at the end of an existing file by default so old
    # history is not replayed into the live window.
    tail_from_start: bool = False

    # Sliding window: fixed buckets rolled into a longer window.
    window_seconds: int = Field(default=60, gt=0)
    bucket_seconds: int = Field(default=10, gt=0)

    # Baseline: how many closed buckets form "normal", and how many are needed
    # before we trust it enough to raise alerts.
    baseline_buckets: int = Field(default=30, ge=3)
    baseline_min_buckets: int = Field(default=6, ge=3)

    # Guards against alerting on tiny samples (3 errors out of 5 lines is 60%
    # but tells us nothing).
    min_errors: int = Field(default=5, ge=0)
    min_total: int = Field(default=50, ge=0)

    # Lower bound on MAD so a perfectly steady baseline cannot make every tiny
    # wobble look infinitely significant.
    mad_floor: float = Field(default=0.002, gt=0)

    # Modified z-score thresholds. 3.5 is the Iglewicz & Hoaglin cut-off; the
    # higher two are our own choices for escalation.
    threshold_warning: float = 3.5
    threshold_high: float = 5.0
    threshold_critical: float = 8.0

    # An incident resolves after this many consecutive normal buckets.
    resolve_after_buckets: int = Field(default=3, ge=1)

    # How much StatsPoint history is kept in memory for /api/stats.
    stats_history_minutes: int = Field(default=60, gt=0)

    # AWS delivery. With aws_endpoint_url set, boto3 talks to a local emulator.
    aws_enabled: bool = True
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    sns_topic_name: str = "claimswatch-alerts"
    cw_log_group: str = "/claimswatch/alerts"
    cw_log_stream: str = "anomalies"

    # Browser origins allowed to call the API directly (the Vite dev proxy
    # makes this unnecessary in development, but it helps other setups).
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def buckets_per_window(self) -> int:
        """Number of buckets that make up one sliding window."""
        return max(1, self.window_seconds // self.bucket_seconds)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
