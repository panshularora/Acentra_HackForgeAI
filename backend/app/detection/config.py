"""Tuning knobs shared by the detectors, built from application settings."""

from dataclasses import dataclass, field

from app.config import Settings
from app.detection.severity import SeverityThresholds


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Tuning knobs for the detectors. See :class:`app.config.Settings` for meanings."""

    window_buckets: int = 6
    bucket_seconds: int = 10
    baseline_buckets: int = 30
    baseline_min_buckets: int = 6
    mad_floor: float = 0.002
    template_mad_floor: float = 1.0
    min_errors: int = 5
    min_total: int = 50
    resolve_after_buckets: int = 3
    thresholds: SeverityThresholds = field(default_factory=SeverityThresholds)
    max_templates: int = 500
    template_similarity: float = 0.5
    sample_line_limit: int = 5
    contributor_limit: int = 3

    @property
    def window_seconds(self) -> int:
        """Duration covered by the sliding window."""
        return self.window_buckets * self.bucket_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "DetectorConfig":
        """Build the detector configuration from application settings."""
        return cls(
            window_buckets=settings.buckets_per_window,
            bucket_seconds=settings.bucket_seconds,
            baseline_buckets=settings.baseline_buckets,
            baseline_min_buckets=settings.baseline_min_buckets,
            mad_floor=settings.mad_floor,
            template_mad_floor=settings.template_mad_floor,
            min_errors=settings.min_errors,
            min_total=settings.min_total,
            resolve_after_buckets=settings.resolve_after_buckets,
            thresholds=SeverityThresholds(
                warning=settings.threshold_warning,
                high=settings.threshold_high,
                critical=settings.threshold_critical,
            ),
            max_templates=settings.max_templates,
            template_similarity=settings.template_similarity,
        )
