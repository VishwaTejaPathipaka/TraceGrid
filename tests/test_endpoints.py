
def create_test_user_and_token(client):
    client.post(
        "/users/register",
        json={
            "username": "endpointuser",
            "email": "endpointuser@example.com",
            "password": "TestPass@123"
        }
    )

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
            "method": "GET"
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
            "method": "POST"
        }
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated API"
    assert response.json()["method"] == "POST"


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
