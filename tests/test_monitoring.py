from contextlib import contextmanager
from datetime import timedelta
import socket
from unittest.mock import Mock, patch

import pytest
from conftest import verify_test_account
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models import APIEndpoint
from app.services import monitor, monitoring_policy, scheduler


def create_user_and_endpoint(client, url="https://jsonplaceholder.typicode.com/users"):
    client.post(
        "/users/register",
        json={
            "username": "monitoruser",
            "email": "monitoruser@example.com",
            "password": "TestPass@123"
        }
    )

    verify_test_account(client, "monitoruser@example.com")
    login_response = client.post(
        "/users/login",
        json={
            "username": "monitoruser",
            "password": "TestPass@123"
        }
    )

    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    endpoint_response = client.post(
        "/endpoints/",
        headers=headers,
        json={
            "name": "Monitoring Test API",
            "url": url,
            "method": "GET"
        }
    )

    endpoint_id = endpoint_response.json()["id"]

    return headers, endpoint_id


@patch("app.routes.monitoring.check_api")
def test_manual_health_check(mock_check, client):
    mock_check.return_value = {
        "status": "UP",
        "status_code": 200,
        "response_time": 120.5
    }

    headers, endpoint_id = create_user_and_endpoint(client)

    response = client.get(
        f"/monitor/{endpoint_id}/check",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert response.json()["status_code"] == 200
    assert response.json()["response_time"] == 120.5


@patch("app.routes.monitoring.check_api")
def test_failed_health_check(mock_check, client):
    mock_check.return_value = {
        "status": "DOWN",
        "status_code": None,
        "response_time": 100.0
    }

    headers, endpoint_id = create_user_and_endpoint(client)

    response = client.get(
        f"/monitor/{endpoint_id}/check",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "DOWN"
    assert response.json()["status_code"] is None


@patch("app.routes.monitoring.check_api")
def test_monitoring_history(mock_check, client):
    mock_check.return_value = {
        "status": "UP",
        "status_code": 200,
        "response_time": 150.0
    }

    headers, endpoint_id = create_user_and_endpoint(client)

    client.get(
        f"/monitor/{endpoint_id}/check",
        headers=headers
    )

    response = client.get(
        f"/monitor/{endpoint_id}/history",
        headers=headers
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["status"] == "UP"


@patch("app.routes.monitoring.check_api")
def test_endpoint_analytics(mock_check, client):
    headers, endpoint_id = create_user_and_endpoint(client)

    mock_check.side_effect = [
        {
            "status": "UP",
            "status_code": 200,
            "response_time": 100.0
        },
        {
            "status": "UP",
            "status_code": 200,
            "response_time": 200.0
        },
        {
            "status": "DOWN",
            "status_code": None,
            "response_time": 300.0
        }
    ]

    for _ in range(3):
        client.get(
            f"/monitor/{endpoint_id}/check",
            headers=headers
        )

    response = client.get(
        f"/monitor/{endpoint_id}/analytics",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["total_checks"] == 3
    assert response.json()["successful_checks"] == 2
    assert response.json()["failed_checks"] == 1
    assert response.json()["average_response_time"] == 200.0
    assert response.json()["uptime_percentage"] == 66.67


def test_dashboard_summary(client):
    headers, endpoint_id = create_user_and_endpoint(client)

    with patch("app.routes.monitoring.check_api") as mock_check:
        mock_check.return_value = {
            "status": "UP",
            "status_code": 200,
            "response_time": 100.0
        }

        client.get(
            f"/monitor/{endpoint_id}/check",
            headers=headers
        )

    response = client.get(
        "/monitor/dashboard/summary",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["total_endpoints"] == 1
    assert response.json()["active_endpoints"] == 1
    assert response.json()["total_checks"] == 1
    assert response.json()["successful_checks"] == 1
    assert response.json()["failed_checks"] == 0
    assert response.json()["uptime_percentage"] == 100.0


def test_monitoring_requires_authentication(client):
    response = client.get("/monitor/dashboard/summary")

    assert response.status_code == 401


@pytest.mark.parametrize("legacy_method", [None, "POST"])
def test_saved_unsafe_endpoint_is_skipped_by_manual_and_scheduled_checks(
    client, monkeypatch, caplog, legacy_method,
):
    address_after_save = "8.8.8.8"

    def resolve_saved_endpoint(host, port, *_):
        address = address_after_save if host == "changed.example.com" else "8.8.8.8"
        return [(socket.AF_INET, (address, port))]

    monkeypatch.setattr(monitoring_policy, "lookup_host", resolve_saved_endpoint)
    headers, endpoint_id = create_user_and_endpoint(client, "https://changed.example.com/")
    allowed_response = client.post("/endpoints/", headers=headers, json={
        "name": "Public endpoint", "url": "https://jsonplaceholder.typicode.com/users",
    })
    assert allowed_response.status_code == 200
    allowed_id = allowed_response.json()["id"]

    with contextmanager(app.dependency_overrides[get_db])() as db:
        monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=db.get_bind()))
        if legacy_method:
            endpoint = db.get(APIEndpoint, endpoint_id)
            endpoint.method = legacy_method
            db.commit()
            expected_error = "Change the monitoring method to GET or HEAD."
        else:
            address_after_save = "127.0.0.1"
            expected_error = "Monitoring requires a public destination."

    request = Mock(return_value=200)
    monkeypatch.setattr(monitor, "_request_status", request)

    response = client.get(f"/monitor/{endpoint_id}/check", headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"].startswith(expected_error)
    request.assert_not_called()

    scheduler.dispatch_due_check(0)
    scheduler.dispatch_due_check(0)

    assert f"Monitoring configuration error for endpoint {endpoint_id}: {expected_error}" in caplog.text
    request.assert_called_once()
    assert client.get(f"/monitor/{endpoint_id}/history", headers=headers).json() == []
    assert client.get(f"/endpoints/{endpoint_id}", headers=headers).json()["configuration_error"].startswith(expected_error)
    allowed_history = client.get(f"/monitor/{allowed_id}/history", headers=headers).json()
    assert len(allowed_history) == 1
    assert allowed_history[0]["status"] == "UP"
    analytics = client.get(f"/monitor/{endpoint_id}/analytics", headers=headers).json()
    assert analytics["total_checks"] == 0
    assert analytics["failed_checks"] == 0
    assert analytics["uptime_percentage"] is None


def test_uptime_excludes_monitoring_errors_but_counts_redirects(client):
    headers, endpoint_id = create_user_and_endpoint(client)
    endpoint_path = f"/monitor/{endpoint_id}"
    summary_path = "/monitor/dashboard/summary"
    assert client.get(f"{endpoint_path}/analytics", headers=headers).json()["uptime_percentage"] is None
    assert client.get(summary_path, headers=headers).json()["uptime_percentage"] is None

    outcomes = [
        {"status": "ERROR", "reason": "dns_timeout", "status_code": None, "response_time": 1000},
        {"status": "REDIRECT", "reason": "redirect", "status_code": 302, "response_time": 20},
        {"status": "UP", "reason": None, "status_code": 200, "response_time": 10},
    ]

    with patch("app.routes.monitoring.check_api", side_effect=outcomes):
        for outcome in outcomes:
            response = client.get(f"{endpoint_path}/check", headers=headers)
            assert response.status_code == 200
            assert response.json()["reason"] == outcome["reason"]
            if outcome["status"] == "ERROR":
                assert client.get(summary_path, headers=headers).json()["uptime_percentage"] is None

    for path in [f"{endpoint_path}/analytics", summary_path]:
        analytics = client.get(path, headers=headers).json()
        assert analytics["total_checks"] == 2
        assert analytics["failed_checks"] == 1
        assert analytics["uptime_percentage"] == 50
        assert analytics["average_response_time"] == 15
    history = client.get(f"{endpoint_path}/history", headers=headers).json()
    assert {row["reason"] for row in history} == {None, "dns_timeout", "redirect"}


@pytest.mark.parametrize("clear_with", ["scheduled_success", "manual_success", "edit"])
def test_configuration_error_lifecycle(client, monkeypatch, clear_with):
    headers, endpoint_id = create_user_and_endpoint(client)
    path = f"/endpoints/{endpoint_id}"
    with contextmanager(app.dependency_overrides[get_db])() as db:
        engine = db.get_bind()
        monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=engine))

    message = "Monitoring requires a public destination."
    monkeypatch.setattr(scheduler, "check_api", Mock(side_effect=monitoring_policy.MonitoringPolicyError(message)))
    scheduler.dispatch_due_check(0)
    endpoint = client.get(path, headers=headers).json()
    assert endpoint["configuration_error"] == message
    assert endpoint["last_schedule_duration_ms"] is not None
    assert client.get(f"/monitor/{endpoint_id}/history", headers=headers).json() == []
    future = scheduler._wall_time() + timedelta(seconds=31)
    monkeypatch.setattr(scheduler, "_wall_time", lambda: future)

    up = {"status": "UP", "status_code": 200, "response_time": 5}
    if clear_with == "scheduled_success":
        monkeypatch.setattr(scheduler, "check_api", Mock(return_value=up))
        scheduler.dispatch_due_check(0)
    elif clear_with == "manual_success":
        with patch("app.routes.monitoring.check_api", return_value=up):
            assert client.get(f"/monitor/{endpoint_id}/check", headers=headers).status_code == 200
    else:
        with engine.connect() as connection:
            pending = scheduler._claim_due_check(connection)
        response = client.put(path, headers=headers, json={
            "name": "Updated endpoint", "url": "https://jsonplaceholder.typicode.com/users",
        })
        assert response.status_code == 200
        with engine.connect() as connection:
            assert scheduler._persist_result(connection, pending, None, message, 0, 0) is None

    assert client.get(path, headers=headers).json()["configuration_error"] is None


def test_manual_check_does_not_advance_the_scheduled_due_time(client):
    headers, endpoint_id = create_user_and_endpoint(client)
    path = f"/endpoints/{endpoint_id}"
    due = client.get(path, headers=headers).json()["next_check_at"]
    with patch("app.routes.monitoring.check_api", return_value={"status": "UP", "status_code": 200, "response_time": 5}):
        assert client.get(f"/monitor/{endpoint_id}/check", headers=headers).status_code == 200
    assert client.get(path, headers=headers).json()["next_check_at"] == due
    row, = client.get(f"/monitor/{endpoint_id}/history", headers=headers).json()
    assert row["scheduled_for"] is None
