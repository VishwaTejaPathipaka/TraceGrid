
from unittest.mock import patch


def create_user_and_endpoint(client):
    client.post(
        "/users/register",
        json={
            "username": "monitoruser",
            "email": "monitoruser@example.com",
            "password": "TestPass@123"
        }
    )

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
            "url": "https://jsonplaceholder.typicode.com/users",
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
