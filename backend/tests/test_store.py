import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from app.alerts.store import _SCHEMA, AlertStore, StatsHistory
from app.models import (
    Alert,
    BaselineBand,
    ChannelDelivery,
    Delivery,
    Explanation,
    ParamValue,
    Severity,
    StatsPoint,
    TemplateRef,
)
from tests.factories import T0, make_alert


@pytest.fixture
def store() -> AlertStore:
    return AlertStore(":memory:")


def test_saved_alert_round_trips(store: AlertStore) -> None:
    alert = make_alert()

    stored = store.save_detection(alert)

    assert stored.to_dict() == alert.to_dict()


def test_update_changes_detection_fields(store: AlertStore) -> None:
    store.save_detection(make_alert())

    updated = store.save_detection(make_alert(status="resolved", resolved_at=T0, score=12.0))

    assert updated.status == "resolved"
    assert updated.resolved_at == T0
    assert updated.score == 12.0


def test_detection_update_preserves_ack_and_delivery(store: AlertStore) -> None:
    store.save_detection(make_alert())
    store.acknowledge("a1")
    store.set_delivery("a1", Delivery(sns=ChannelDelivery("sent", "msg-1")))

    after = store.save_detection(make_alert(severity=Severity.CRITICAL, score=15.0))

    assert after.acknowledged
    assert after.delivery.sns.status == "sent"
    assert after.delivery.sns.message_id == "msg-1"


def test_detection_update_can_reset_delivery_for_a_new_transition(store: AlertStore) -> None:
    store.save_detection(make_alert())
    store.acknowledge("a1")
    store.set_delivery("a1", Delivery(sns=ChannelDelivery("sent", "msg-1")))

    after = store.save_detection(
        make_alert(status="resolved", resolved_at=T0, delivery=Delivery()), reset_delivery=True
    )

    assert after.acknowledged
    assert after.delivery.sns == ChannelDelivery("pending")
    assert after.delivery.cloudwatch == ChannelDelivery("pending")


def test_list_recent_is_newest_first_and_limited(store: AlertStore) -> None:
    for minute in range(5):
        store.save_detection(make_alert(f"a{minute}", opened_at=T0 + timedelta(minutes=minute)))

    recent = store.list_recent(limit=3)

    assert [a.id for a in recent] == ["a4", "a3", "a2"]


def test_acknowledge_unknown_alert_returns_none(store: AlertStore) -> None:
    assert store.acknowledge("missing") is None
    assert store.set_delivery("missing", Delivery()) is None


def test_alerts_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "data" / "alerts.db"
    first = AlertStore(path)
    first.save_detection(make_alert())
    first.close()

    reopened = AlertStore(path)

    assert reopened.get("a1") is not None
    reopened.close()


def point(seconds: int) -> StatsPoint:
    return StatsPoint(T0 + timedelta(seconds=seconds), 100, 2, 0.02, None, None, None, None)


def test_stats_history_returns_recent_window() -> None:
    history = StatsHistory(max_points=1000)
    for seconds in range(0, 900, 10):
        history.append(point(seconds))

    last_five_minutes = history.since(minutes=5)

    assert len(last_five_minutes) == 30
    assert last_five_minutes[0].ts < last_five_minutes[-1].ts


def test_stats_history_is_bounded() -> None:
    history = StatsHistory(max_points=3)
    for seconds in range(0, 50, 10):
        history.append(point(seconds))

    assert [p.ts.second for p in history.since(minutes=60)] == [20, 30, 40]


def test_empty_stats_history() -> None:
    assert StatsHistory(max_points=3).since(minutes=10) == []


def explained_alert() -> Alert:
    return make_alert(
        explanation=Explanation(
            detector="error_spike",
            template=TemplateRef(
                "7", 'ERROR member-auth msg="login failed" ip=<IP>', "member-auth"
            ),
            baseline_band=BaselineBand(median=0.0, upper=5.19, unit="errors/60s"),
            observed=179.0,
            first_bad_line="2026-09-28T13:00:00Z ERROR member-auth ip=10.4.2.17",
            params=[ParamValue("source_ip", "10.4.2.17", 179, 1.0)],
        )
    )


def test_explanation_round_trips(store: AlertStore) -> None:
    alert = explained_alert()

    stored = store.save_detection(alert)

    assert stored.explanation == alert.explanation
    assert stored.to_dict()["params"] == [
        {"name": "source_ip", "value": "10.4.2.17", "count": 179, "share": 1.0}
    ]


def test_alert_without_explanation_serialises_nulls(store: AlertStore) -> None:
    data = store.save_detection(make_alert()).to_dict()

    assert data["detector"] is None
    assert data["template"] is None
    assert data["baseline_band"] is None
    assert data["observed"] is None
    assert data["first_bad_line"] is None
    assert data["params"] == []


def test_database_from_before_explanations_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(_SCHEMA.replace(",\n    explanation      TEXT", ""))
    old.execute(
        "INSERT INTO alerts VALUES ('old1', 'resolved', 'HIGH', 6.0, 0.1, 0.02, "
        "'2026-09-28T13:00:00Z', '2026-09-28T13:00:00Z', NULL, 'old alert', "
        "'{}', '[]', 0, '{}')"
    )
    old.commit()
    old.close()

    migrated = AlertStore(path)

    old_alert = migrated.get("old1")
    assert old_alert is not None
    assert old_alert.explanation == Explanation()
    assert migrated.save_detection(explained_alert()).explanation.detector == "error_spike"


def test_resolve_stale_open_closes_only_open_incidents(store: AlertStore) -> None:
    store.save_detection(make_alert("open-1"))
    store.save_detection(make_alert("open-2"))
    store.save_detection(make_alert("done", status="resolved", resolved_at=T0))
    now = T0 + timedelta(hours=1)

    assert store.resolve_stale_open(now) == 2

    assert all(a.status == "resolved" for a in store.list_recent())
    assert store.get("open-1").resolved_at == now  # type: ignore[union-attr]
    assert store.get("done").resolved_at == T0  # type: ignore[union-attr]
