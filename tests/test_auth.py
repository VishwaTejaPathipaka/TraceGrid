
def test_register_user(client):
    response = client.post(
        "/users/register",
        json={
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "TestPass@123"
        }
    )

    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    assert response.json()["email"] == "testuser@example.com"


def test_duplicate_registration(client):
    user = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "TestPass@123"
    }

    client.post("/users/register", json=user)
    response = client.post("/users/register", json=user)

    assert response.status_code == 400
    assert response.json()["detail"] == "Username or email already registered"


def test_login_success(client):
    client.post(
        "/users/register",
        json={
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "TestPass@123"
        }
    )

    response = client.post(
        "/users/login",
        json={
            "username": "testuser",
            "password": "TestPass@123"
        }
    )

    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post(
        "/users/register",
        json={
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "TestPass@123"
        }
    )

    response = client.post(
        "/users/login",
        json={
            "username": "testuser",
            "password": "WrongPass@123"
        }
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_register_invalid_email(client):
    response = client.post(
        "/users/register",
        json={
            "username": "testuser",
            "email": "invalid-email",
            "password": "TestPass@123"
        }
    )

    assert response.status_code == 422
