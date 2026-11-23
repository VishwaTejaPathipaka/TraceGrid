from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from conftest import fail_probe_commit

from test_websocket_monitoring import account, bearer, connected


DOWN = {"status": "DOWN", "status_code": 503, "reason": "http_error", "response_time": 24.5}
UP = {"status": "UP", "status_code": 204, "response_time": 11.25}
ERROR = {"status": "ERROR", "status_code": None, "reason": "dns_timeout", "response_time": 100.0}
REDIRECT = {"status": "REDIRECT", "status_code": 302, "reason": "redirect", "response_time": 17.5}


@pytest.fixture
def probes(client, monkeypatch):
    token, endpoint_id = account(client, "incident_owner")
    headers = bearer(token)
    monitor = Mock()
    monkeypatch.setattr("app.routes.monitoring.check_api", monitor)

    def run(*results):
        for result in results:
            monitor.return_value = result
            response = client.get(f"/monitor/{endpoint_id}/check", headers=headers)
            assert response.status_code == 200

    return token, headers, endpoint_id, run


def items(client, headers, **filters):
    response = client.get("/incidents/", headers=headers, params=filters)
    assert response.status_code == 200
    return response.json()["items"]


def action(client, headers, incident, decision):
    return client.post(f"/incidents/{incident['id']}/{decision}", headers=headers)


def test_threshold_error_exclusion_duplicate_prevention_and_recovery(client, probes):
    _, headers, endpoint_id, run = probes
    run(ERROR, ERROR, ERROR, DOWN, DOWN)
    assert items(client, headers) == []
    run(ERROR, DOWN, DOWN, REDIRECT)
    incident, = items(client, headers)
    assert incident["endpoint_id"] == endpoint_id
    assert incident["status"] == "open"
    assert incident["severity"] == "critical"
    assert incident["failure_reason"] == "http_error"
    assert incident["failure_http_status"] == 503
    assert incident["detected_at"] >= incident["started_at"]
    run(ERROR)
    assert items(client, headers)[0]["status"] == "open"
    run(UP)
    resolved, = items(client, headers, status="resolved")
    assert resolved["id"] == incident["id"]
    assert resolved["resolution"] == "recovered"
    assert resolved["resolved_at"] >= resolved["detected_at"]
    assert resolved["recovery_http_status"] == 204
    assert resolved["recovery_response_ms"] == 11.25
    overview = client.get("/incidents/summary", headers=headers).json()
    assert overview["active_count"] == overview["affected_endpoints"] == 0
    assert overview["recently_resolved"] == [resolved]


def test_success_resets_streak_and_redirects_are_unsuccessful(client, probes):
    _, headers, _, run = probes
    run(DOWN, DOWN, UP, REDIRECT, REDIRECT)
    assert items(client, headers) == []
    run(REDIRECT)
    incident, = items(client, headers)
    assert (incident["severity"], incident["failure_reason"], incident["failure_http_status"]) == (
        "warning", "redirect", 302,
    )


def test_lifecycle_owner_isolation_and_filtering(client, probes):
    _, headers, endpoint_id, run = probes
    other = bearer(account(client, "incident_other", endpoint=False))
    run(DOWN, DOWN, DOWN)
    incident, = items(client, headers)
    assert items(client, other, incident_id=incident["id"]) == []
    assert client.get("/incidents/summary", headers=other).json()["active_count"] == 0
    assert action(client, other, incident, "acknowledge").status_code == 404
    assert action(client, other, incident, "resolve").status_code == 404
    assert client.get("/incidents/").status_code in (401, 403)

    acknowledged = action(client, headers, incident, "acknowledge")
    assert acknowledged.status_code == 200
    timestamp = acknowledged.json()["acknowledged_at"]
    assert timestamp
    assert action(client, headers, incident, "acknowledge").json()["acknowledged_at"] == timestamp
    today = datetime.now(timezone.utc).date().isoformat()
    assert items(client, headers, endpoint_id=endpoint_id, status="acknowledged",
                 from_date=today, to_date=today) == [acknowledged.json()]
    assert items(client, headers, status="open") == []
    assert items(client, headers, to_date="2000-01-01") == []
    assert client.get("/incidents/", headers=headers, params={"from_date": today, "to_date": "2000-01-01"}).status_code == 422
    summary = client.get("/incidents/summary", headers=headers).json()
    assert summary["active_count"] == summary["affected_endpoints"] == 1

    resolved = action(client, headers, incident, "resolve").json()
    assert resolved["status"] == "resolved"
    assert resolved["resolution"] == "manual"
    assert resolved["acknowledged_at"] == timestamp
    assert resolved["recovery_http_status"] is None
    assert action(client, headers, incident, "resolve").json() == resolved
    assert action(client, headers, incident, "acknowledge").status_code == 409
    run(DOWN, DOWN)
    assert len(items(client, headers)) == 1
    run(DOWN)
    assert len(items(client, headers)) == 2


def test_incident_websocket_lifecycle_reaches_only_owner(client, probes):
    token, headers, endpoint_id, run = probes
    other_token, other_endpoint = account(client, "incident_socket_other")
    run(DOWN, DOWN)
    with connected(client, token) as owner, connected(client, other_token) as other:
        run(DOWN)
        incident, = items(client, headers)
        expected = {"type": "incident.updated", "incident_id": incident["id"], "endpoint_id": endpoint_id}
        assert owner.receive_json() == {**expected, "action": "created"}
        assert action(client, headers, incident, "acknowledge").status_code == 200
        assert owner.receive_json() == {**expected, "action": "acknowledged"}
        run(UP)
        assert owner.receive_json() == {**expected, "action": "resolved"}
        assert client.get(f"/monitor/{other_endpoint}/check", headers=bearer(other_token)).status_code == 200
        assert other.receive_json() == {"type": "monitoring.updated", "endpoint_id": other_endpoint}


def test_probe_and_incident_rollback_together(client, probes, monkeypatch):
    _, headers, endpoint_id, run = probes
    run(DOWN, DOWN)
    with monkeypatch.context() as patch:
        fail_probe_commit(patch)
        assert client.get(f"/monitor/{endpoint_id}/check", headers=headers).status_code == 503
    assert items(client, headers) == []
    assert len(client.get(f"/monitor/{endpoint_id}/history", headers=headers).json()) == 2
    run(DOWN)
    assert len(items(client, headers)) == 1
    assert len(client.get(f"/monitor/{endpoint_id}/history", headers=headers).json()) == 3
