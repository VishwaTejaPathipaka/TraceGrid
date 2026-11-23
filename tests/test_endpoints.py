import pytest
from conftest import verify_test_account

def create_test_user_and_token(client):
    client.post(
        "/users/register",
        json={
            "username": "endpointuser",
            "email": "endpointuser@example.com",
            "password": "TestPass@123"
        }
    )

    verify_test_account(client, "endpointuser@example.com")
    response = client.post(
        "/users/login",
        json={
            "username": "endpointuser",
            "password": "TestPass@123"
        }
    )

    return response.json()["access_token"]


def test_create_endpoint(client):
    token = create_test_user_and_token(client)

    response = client.post(
        "/endpoints/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Test API",
            "url": "https://jsonplaceholder.typicode.com/users",
        }
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Test API"
    assert response.json()["method"] == "GET"
    assert response.json()["is_active"] is True


def test_get_endpoints(client):
    token = create_test_user_and_token(client)

    client.post(
        "/endpoints/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Test API",
            "url": "https://jsonplaceholder.typicode.com/users",
            "method": "GET"
        }
    )

    response = client.get(
        "/endpoints/",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Test API"


def test_update_endpoint(client):
    token = create_test_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/endpoints/",
        headers=headers,
        json={
            "name": "Old API",
            "url": "https://jsonplaceholder.typicode.com/users",
            "method": "GET"
        }
    )

    endpoint_id = create_response.json()["id"]

    response = client.put(
        f"/endpoints/{endpoint_id}",
        headers=headers,
        json={
            "name": "Updated API",
            "url": "https://jsonplaceholder.typicode.com/posts",
            "method": "HEAD"
        }
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated API"
    assert response.json()["method"] == "HEAD"


@pytest.mark.parametrize("url, method, message", [
    ("https://jsonplaceholder.typicode.com/", "POST", "GET"),
    ("http://127.0.0.1/", "GET", "public destination"),
    ("http://[::1]/", "HEAD", "public destination"),
    ("https://user:example@example.com/", "GET", "Remove credentials"),
])
def test_reject_unsafe_endpoint_configuration(client, url, method, message):
    headers = {"Authorization": f"Bearer {create_test_user_and_token(client)}"}
    response = client.post("/endpoints/", headers=headers, json={
        "name": "Rejected endpoint", "url": url, "method": method,
    })

    assert response.status_code == 422
    assert message in str(response.json()["detail"])


def test_unsafe_update_keeps_existing_configuration(client):
    headers = {"Authorization": f"Bearer {create_test_user_and_token(client)}"}
    original_url = "https://jsonplaceholder.typicode.com/"
    created = client.post("/endpoints/", headers=headers, json={
        "name": "Existing endpoint", "url": original_url,
    }).json()
    endpoint_path = f"/endpoints/{created['id']}"
    response = client.put(endpoint_path, headers=headers, json={
        "name": "Existing endpoint", "url": "http://169.254.169.254/", "method": "HEAD",
    })

    assert response.status_code == 422
    assert client.get(endpoint_path, headers=headers).json() == created


def test_endpoint_save_reports_dns_timeout(client, monkeypatch):
    def timed_out(*args):
        raise TimeoutError()

    monkeypatch.setattr("app.services.monitoring_policy.lookup_host", timed_out)
    headers = {"Authorization": f"Bearer {create_test_user_and_token(client)}"}
    response = client.post("/endpoints/", headers=headers, json={
        "name": "Endpoint with slow DNS", "url": "https://jsonplaceholder.typicode.com/",
    })

    assert response.status_code == 503
    assert "lookup timed out" in response.json()["detail"]
    assert client.get("/endpoints/", headers=headers).json() == []


def test_delete_endpoint(client):
    token = create_test_user_and_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/endpoints/",
        headers=headers,
        json={
            "name": "Test API",
            "url": "https://jsonplaceholder.typicode.com/users",
            "method": "GET"
        }
    )

    endpoint_id = create_response.json()["id"]

    response = client.delete(
        f"/endpoints/{endpoint_id}",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Endpoint deleted successfully"


def test_endpoints_require_authentication(client):
    response = client.get("/endpoints/")

    assert response.status_code == 401
