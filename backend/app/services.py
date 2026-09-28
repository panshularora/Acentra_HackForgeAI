"""Construct and hold the long-lived components the API and pipeline share."""

from dataclasses import dataclass

from app.alerts.store import AlertStore, StatsHistory
from app.api.ws import ConnectionManager
from app.config import Settings
from app.detection.detector import Detector, DetectorConfig
from app.ingest.parser import LogParser
from app.ingest.tailer import FileTailer
from app.pipeline import Pipeline


@dataclass
class Services:
    """Everything a request handler might need, created once per application."""

    settings: Settings
    store: AlertStore
    stats: StatsHistory
    clients: ConnectionManager
    tailer: FileTailer
    parser: LogParser
    detector: Detector
    pipeline: Pipeline

    def close(self) -> None:
        """Release files and database connections."""
        self.tailer.close()
        self.store.close()


def build_services(settings: Settings) -> Services:
    """Wire the components together from settings."""
    detector = Detector(DetectorConfig.from_settings(settings))
    store = AlertStore(settings.db_path)
    stats = StatsHistory(settings.stats_history_minutes * 60 // settings.bucket_seconds)
    clients = ConnectionManager()
    tailer = FileTailer(
        settings.log_path,
        poll_interval=settings.tail_poll_seconds,
        from_start=settings.tail_from_start,
    )
    parser = LogParser()
    pipeline = Pipeline(
        tailer=tailer,
        parser=parser,
        detector=detector,
        store=store,
        stats=stats,
        clients=clients,
    )
    return Services(settings, store, stats, clients, tailer, parser, detector, pipeline)
