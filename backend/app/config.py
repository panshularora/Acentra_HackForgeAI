"""Runtime configuration, read once from environment variables (or a .env file).

Every tunable number in the service lives here so the detector, the tailer and
the AWS publisher never carry their own magic constants.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repository root, so `.env` loads whether uvicorn
# is started from the repo root or from backend/.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", str(_REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    # Alerting scores each log template's error count per window; its MAD floor
    # is in errors per window, so a template that never errs needs a real burst
    # (6 errors reach WARNING at the defaults), not one stray line.
    template_mad_floor: float = Field(default=1.0, gt=0)

    # Drain3 template mining: cap on templates kept in memory (least recently
    # seen are dropped), and how similar two lines must be to share a template.
    max_templates: int = Field(default=500, ge=1)
    template_similarity: float = Field(default=0.5, gt=0, le=1)

    # Modified z-score thresholds. 3.5 is the Iglewicz & Hoaglin cut-off; the
    # higher two are our own choices for escalation.
    threshold_warning: float = 3.5
    threshold_high: float = 5.0
    threshold_critical: float = 8.0

    # An incident resolves after this many consecutive normal buckets.
    resolve_after_buckets: int = Field(default=3, ge=1)

    # Silence: a steady template (low CV of inter-arrival gaps) is overdue.
    silence_factor: float = Field(default=3.0, gt=1)
    silence_min_seconds: float = Field(default=20.0, gt=0)
    silence_max_cv: float = Field(default=0.25, gt=0)
    silence_min_gaps: int = Field(default=6, ge=2)

    # New-pattern: unseen ERROR/WARN template, minimum occurrences after warm-up.
    new_pattern_min_count: int = Field(default=2, ge=1)

    # Flow-break: validated claim still pending after this many seconds.
    flow_timeout_seconds: float = Field(default=5.0, gt=0)
    flow_map_cap: int = Field(default=10_000, ge=16)

    # How much StatsPoint history is kept in memory for /api/stats.
    stats_history_minutes: int = Field(default=60, gt=0)

    # AWS delivery. With aws_endpoint_url set, boto3 talks to a local emulator.
    aws_enabled: bool = True
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    # Credentials read here (from the environment or .env) are passed to boto3
    # explicitly, because pydantic-settings does not export .env values to the
    # process environment boto3 reads. Unset, boto3 uses its normal chain.
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    sns_topic_name: str = "claimswatch-alerts"
    # An existing topic to publish to. When set, the topic is not created, so
    # the credentials only need sns:Publish on it.
    sns_topic_arn: str | None = None
    cw_enabled: bool = True
    cw_log_group: str = "/claimswatch/alerts"
    cw_log_stream: str = "anomalies"

    # Browser origins allowed to call the API directly (the Vite dev proxy
    # makes this unnecessary in development, but it helps other setups).
    cors_origins: list[str] = ["http://localhost:5173"]
    cors_origin_regex: str | None = None

    # Production image: serve frontend/dist from this process and write demo
    # traffic into log_path so a single container is a full live demo.
    serve_dashboard: bool = False
    demo_loggen: bool = False

    @property
    def buckets_per_window(self) -> int:
        """Number of buckets that make up one sliding window."""
        return max(1, self.window_seconds // self.bucket_seconds)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
