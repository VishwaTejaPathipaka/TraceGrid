from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.database import get_db
from app.main import app
from app.models import Incident, MonitoringHistory
from test_websocket_monitoring import account, bearer


REPORT = "/analytics/report"


@pytest.fixture
def analytics(client, monkeypatch):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    end = now + timedelta(seconds=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("app.services.advanced_analytics.datetime", Clock)
    owner, target = account(client, "analytics_owner")
    other, private = account(client, "analytics_other")
    headers = bearer(owner)

    def new_endpoint(name):
        response = client.post("/endpoints/", headers=headers,
                               json={"name": name, "url": "https://jsonplaceholder.typicode.com/"})
        assert response.status_code == 200
        return response.json()["id"]

    return end, headers, target, bearer(other), private, new_endpoint


def database():
    return contextmanager(app.dependency_overrides[get_db])()


def seed(rows):
    with database() as db:
        db.add_all([MonitoringHistory(endpoint_id=id, checked_at=at, status=status, response_time=ms,
                                      status_code=code, reason=reason)
                    for id, at, status, ms, code, reason in rows])
        db.commit()


def report(client, headers, **params):
    result = client.get(REPORT, headers=headers, params=params)
    assert result.status_code == 200
    return result.json()


def test_endpoint_trend_uses_exact_time_and_separates_failure_error_and_recording_gaps(client, analytics):
    end, owner, id, _, _, _ = analytics
    start = end - timedelta(hours=1)
    times = [start + timedelta(seconds=offset, microseconds=123456) for offset in (5, 28, 45, 57, 70, 190, 220)]
    outcomes = [
        ("UP", 10, 200, None), ("UP", 5, 204, None), ("DOWN", 500, 503, "http_error"),
        ("UP", 40, 200, None), ("ERROR", 800, None, "dns_timeout"), ("UP", 65, 200, None),
        ("UP", float("inf"), 200, None),
    ]
    seed([(id, at, *outcome) for at, outcome in zip(times, outcomes)])
    seed([(id, start - timedelta(microseconds=1), "DOWN", 15, 404, None),
          (id, end, "DOWN", 20, 404, None)])
    payload = report(client, owner, endpoint_id=id, range="1h", compare=False)
    endpoint = payload["endpoint"]
    assert payload["comparison"] is None
    assert endpoint["availability"] == {"successful": 5, "unsuccessful": 1, "monitoring_errors": 1}
    assert endpoint["uptime"] == pytest.approx(100 * 5 / 6)
    assert endpoint["latency"]["samples"] == 5
    assert endpoint["latency"]["average"] == 124
    assert endpoint["latency"]["p95"] is None
    points = endpoint["trend"]
    assert all(point["status"] != "ERROR" for point in points)
    assert [datetime.fromisoformat(point["checked_at"]) for point in points] == [
        times[i] for i in (0, 1, 2, 3, 5)]
    assert points[0]["segment"] == points[1]["segment"]
    assert points[2]["segment"] is None
    assert len({points[0]["segment"], points[3]["segment"], points[4]["segment"]}) == 3
    assert any(bucket["gaps"] > 0 for bucket in endpoint["timeline"])
    assert len(endpoint["timeline"]) < payload["window"]["bucket_count"]
    assert payload["incidents"]["overlapping"] == 0


def test_histogram_exact_percentiles_and_bounded_points_preserve_tail(client, analytics):
    end, owner, id, _, _, _ = analytics
    start = end - timedelta(hours=1)
    milliseconds = [*range(99), 10000]
    seed([(id, start + timedelta(seconds=10, milliseconds=i * 10), "UP", value, 200, None)
          for i, value in enumerate(milliseconds)])
    endpoint = report(client, owner, endpoint_id=id, range="1h")["endpoint"]
    latency = endpoint["latency"]
    assert latency == {"samples": 100, "average": pytest.approx(sum(milliseconds) / 100),
                       "median": 49.5, "p95": pytest.approx(94.05), "p99": pytest.approx(197.02), "maximum": 10000}
    assert len(endpoint["trend"]) <= 4
    assert max(item["response_time"] for item in endpoint["trend"]) == 10000
    assert endpoint["histogram"][0] == {"lower": 0, "upper": 50, "count": 50}
    assert endpoint["histogram"][-1] == {"lower": 5000, "upper": None, "count": 1}
    assert sum(row["count"] for row in endpoint["histogram"]) == 100


def test_timeline_individual_checks_paginate_ties_and_limits_and_enforce_owner(client, analytics):
    end, owner, id, outsider, private, _ = analytics
    at = end - timedelta(hours=1) + timedelta(seconds=2, microseconds=54545)
    seed([(id, at, "ERROR" if i == 0 else "UP", 0 if i == 0 else 42,
           None if i == 0 else 200, "dns_resolver" if i == 0 else None) for i in range(30)])
    path = f"/analytics/endpoints/{id}/checks"
    params = {"range": "1h", "end": end.isoformat(), "bucket": 0}
    first = client.get(path, headers=owner, params=params).json()
    assert len(first["items"]) == 24
    assert first["items"][0]["reason"] == "dns_resolver"
    assert first["items"][0]["response_time"] == 0
    assert first["items"][0]["status"] == "ERROR"
    cursor = first["next_cursor"]
    second = client.get(path, headers=owner, params={**params, "after_at": cursor["at"], "after_id": cursor["id"]}).json()
    assert len(second["items"]) == 6 and second["next_cursor"] is None
    assert first["items"][-1]["id"] < second["items"][0]["id"]
    assert client.get(path, headers=outsider, params=params).status_code == 404
    assert client.get(path, headers=owner, params={**params, "bucket": 60}).status_code == 422
    assert client.get(path, headers=owner, params={**params, "after_id": cursor["id"]}).status_code == 422
    assert client.get(path, headers=owner, params={**params, "end": end.replace(tzinfo=None).isoformat()}).status_code == 422
    assert client.get(REPORT, headers=owner, params={"endpoint_id": private}).status_code == 404
    assert client.get(REPORT, headers=owner, params={"range": "365d"}).status_code == 422
    assert client.get(REPORT, headers=owner, params={"metric": "drop"}).status_code == 422
    assert client.get(REPORT).status_code in (401, 403)


def test_cross_endpoint_comparison_nulls_counts_sorting_and_ranges(client, analytics):
    end, owner, id, outsider, private, new = analytics
    empty = new("No checks")
    failed = new("All fails")
    old = end - timedelta(hours=3)
    now = end - timedelta(minutes=2)
    seed([(id, now, "UP", 40, 200, None), (id, now, "REDIRECT", 60, 302, "redirect"),
          (id, old, "UP", 90, 200, None), (empty, now, "ERROR", 100, None, "dns_timeout"),
          (failed, now, "DOWN", 25, 500, "http_error"), (private, now, "UP", 1, 200, None)])
    comparison = report(client, owner, range="1h")["comparison"]
    assert [(row["id"], row["value"], row["samples"]) for row in comparison["items"]] == [
        (id, 50, 2), (failed, 0, 1), (empty, None, 0)]
    latency = report(client, owner, range="6h", metric="latency", descending=False)["comparison"]
    assert [(row["id"], row["value"], row["samples"]) for row in latency["items"]] == [
        (failed, 25, 1), (id, pytest.approx(190 / 3), 3), (empty, None, 0)]
    for metric, value in (("successful", 2), ("unsuccessful", 1), ("measured", 3)):
        items = report(client, owner, range="7d", metric=metric)["comparison"]["items"]
        assert next(entry for entry in items if entry["id"] == id)["value"] == value
    no_data = report(client, owner, endpoint_id=empty, range="24h")["endpoint"]
    assert no_data["uptime"] is None and no_data["trend"] == []
    assert no_data["latency"]["samples"] == 0 and no_data["latency"]["average"] is None
    assert report(client, outsider)["comparison"]["total"] == 1


def test_incident_analytics_overlap_resolution_and_boundary_rules(client, analytics):
    end, owner, id, _, private, new = analytics
    start = end - timedelta(hours=1)
    second = new("Additional endpoint")

    def incident(endpoint_id, started, detected, resolved, resolution):
        from app.models import APIEndpoint
        endpoint = db.get(APIEndpoint, endpoint_id)
        return Incident(owner_id=endpoint.user_id, endpoint_id=endpoint.id, endpoint_name=endpoint.name,
                        title="Availability fixture", status="resolved" if resolved else "open",
                        severity="critical", failure_reason="http_error", started_at=started,
                        detected_at=detected, resolved_at=resolved, resolution=resolution)

    with database() as db:
        db.add_all([
            incident(id, start - timedelta(minutes=5), start - timedelta(minutes=4), start + timedelta(minutes=5), "recovered"),
            incident(id, start + timedelta(minutes=10), start + timedelta(minutes=11), start + timedelta(minutes=20), "manual"),
            incident(second, start - timedelta(minutes=8), start - timedelta(minutes=7), start, "manual"),
            incident(second, end, end, None, None),
            incident(private, start, start + timedelta(minutes=1), start + timedelta(minutes=8), "recovered"),
        ])
        db.commit()
    result = report(client, owner, range="1h")["incidents"]
    assert result == {"overlapping": 2, "opened": 1, "recovered": 1, "manually_resolved": 2,
                      "average_recovery_seconds": 600, "affected": [{"id": id, "name": "analytics_owner endpoint", "incidents": 2}]}
    scoped = report(client, owner, range="1h", endpoint_id=second)["incidents"]
    assert scoped["overlapping"] == 0 and scoped["manually_resolved"] == 1
    assert scoped["average_recovery_seconds"] is None


def test_overview_ignores_invalid_latency_without_losing_availability(client, analytics):
    end, owner, id, _, _, _ = analytics
    seed([(id, end - timedelta(seconds=2), "UP", float("inf"), 200, None),
          (id, end - timedelta(seconds=3), "ERROR", 95, None, "dns_timeout")])
    summary = client.get("/monitor/dashboard/summary", headers=owner).json()
    assert summary["total_checks"] == 1 and summary["latency_samples"] == 0
    assert summary["uptime_percentage"] == 100
    recent = client.get("/monitor/dashboard/recent", headers=owner).json()
    assert recent[0]["response_time"] is None
