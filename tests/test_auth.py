from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, update

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.token import AccountToken
from app.models.users import User
from app.security import create_access_token, verify_password
from app.services.account_email import deliver_account_email
from conftest import email_tokens, verify_test_account


EMAIL = "testuser@example.com"
PASSWORD = "TestPass@123"
NEW_PASSWORD = "NewPassword@456"
ACCOUNT = {"username": "testuser", "email": EMAIL, "password": PASSWORD}


def post(client, action, **payload):
    return client.post(f"/users/{action}", json=payload)


def login(client, password=PASSWORD):
    return post(client, "login", username=ACCOUNT["username"], password=password)


def database():
    return contextmanager(app.dependency_overrides[get_db])()


def test_registration_requires_mailbox_and_password(client):
    assert post(client, "register", **ACCOUNT).status_code == 202
    assert login(client).status_code == 403
    token, = email_tokens(EMAIL, "verify-email")
    assert post(client, "verify-email", token=token, password=NEW_PASSWORD).status_code == 400
    assert login(client).status_code == 403
    assert post(client, "verify-email", token=token, password=PASSWORD).status_code == 200
    assert post(client, "verify-email", token=token, password=PASSWORD).status_code == 400
    assert login(client).status_code == 200
    assert login(client, NEW_PASSWORD).status_code == 401


def test_registration_hides_duplicate_email_and_username(client):
    original = post(client, "register", **ACCOUNT)
    for payload in [{**ACCOUNT, "username": "another", "email": EMAIL.upper()},
                    {**ACCOUNT, "email": "another@example.com"}]:
        duplicate = post(client, "register", **payload)
        assert (duplicate.status_code, duplicate.json()) == (original.status_code, original.json())
    with database() as db:
        assert len(db.scalars(select(User)).all()) == 1
    assert len(email_tokens(EMAIL, "verify-email")) == 1


@pytest.mark.parametrize("action", ["resend-verification", "forgot-password"])
def test_link_requests_have_generic_responses_and_resend_cooldown(client, action):
    post(client, "register", **ACCOUNT)
    with database() as db:
        db.execute(update(AccountToken).values(issued_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
        db.commit()
    existing = post(client, action, email=EMAIL.upper())
    missing = post(client, action, email="unknown@example.com")
    repeated = post(client, action, email=EMAIL)
    assert existing.status_code == missing.status_code == repeated.status_code == 202
    assert existing.json() == missing.json() == repeated.json()
    page = "verify-email" if action == "resend-verification" else "reset-password"
    tokens = email_tokens(EMAIL, page)
    assert len(tokens) == (2 if page == "verify-email" else 1)
    if page == "verify-email":
        attempts = [post(client, page, token=token, password=PASSWORD).status_code for token in tokens]
        assert sorted(attempts) == [200, 400]


@pytest.mark.parametrize("purpose,page", [("verify", "verify-email"), ("reset", "reset-password")])
def test_expired_or_wrong_purpose_link_cannot_be_used(client, purpose, page):
    post(client, "register", **ACCOUNT)
    post(client, "forgot-password", email=EMAIL)
    token, = email_tokens(EMAIL, page)
    other_page = "verify-email" if page == "reset-password" else "reset-password"
    assert post(client, other_page, token=token, password=PASSWORD).status_code == 400
    with database() as db:
        db.execute(update(AccountToken).where(AccountToken.purpose == purpose).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    assert post(client, page, token=token, password=PASSWORD).status_code == 400


def test_invalid_input_does_not_echo_password_or_token(client):
    assert post(client, "register", **{**ACCOUNT, "email": "bad-email"}).status_code == 422
    assert post(client, "forgot-password", email="bad-email").status_code == 422
    response = post(client, "reset-password", token="private-token", password="short-secret"[:9])
    assert response.status_code == 422
    assert "private-token" not in response.text
    assert "short-sec" not in response.text


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_reset_is_single_use_and_invalidates_http_and_websocket_sessions(client):
    post(client, "register", **ACCOUNT)
    verify_test_account(client, EMAIL)
    access_token = login(client).json()["access_token"]
    legacy_token = create_access_token({"sub": ACCOUNT["username"]})
    post(client, "forgot-password", email=EMAIL)
    token, = email_tokens(EMAIL, "reset-password")
    with database() as db:
        assert db.scalar(select(AccountToken.digest)) != token
    with client.websocket_connect("/ws/monitoring") as socket:
        socket.send_json({"type": "authenticate", "token": access_token})
        assert socket.receive_json() == {"type": "monitoring.ready"}
        assert post(client, "reset-password", token=token, password="short").status_code == 422
        assert post(client, "reset-password", token=token, password=NEW_PASSWORD).status_code == 200
        assert socket.receive()["code"] == 4401
    assert post(client, "reset-password", token=token, password=PASSWORD).status_code == 400
    for invalidated in (access_token, legacy_token):
        assert client.get("/endpoints/", headers=bearer(invalidated)).status_code == 401
    assert login(client).status_code == 401
    new_token = login(client, NEW_PASSWORD).json()["access_token"]
    assert client.get("/endpoints/", headers=bearer(new_token)).status_code == 200
    with database() as db:
        stored = db.scalar(select(User.hashed_password))
        assert stored != NEW_PASSWORD and verify_password(NEW_PASSWORD, stored)


def test_reset_recovers_pending_account_without_bypassing_verification(client):
    post(client, "register", **ACCOUNT)
    post(client, "forgot-password", email=EMAIL)
    reset_token, = email_tokens(EMAIL, "reset-password")
    verify_token, = email_tokens(EMAIL, "verify-email")
    result = post(client, "reset-password", token=reset_token, password=NEW_PASSWORD)
    assert result.status_code == 200
    assert "Verify your email" in result.json()["message"]
    assert login(client, NEW_PASSWORD).status_code == 403
    assert post(client, "verify-email", token=verify_token, password=NEW_PASSWORD).status_code == 200
    assert login(client, NEW_PASSWORD).status_code == 200


def test_smtp_delivery_uses_tls_and_configured_frontend_with_mock_relay(monkeypatch):
    relay = MagicMock()
    monkeypatch.setattr("app.services.account_email.smtplib.SMTP", relay)
    monkeypatch.setattr(settings, "EMAIL_DELIVERY", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_TLS", "starttls")
    monkeypatch.setattr(settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(settings, "ACCOUNT_LINK_BASE_URL", "https://tracegrid.example.com")
    deliver_account_email(EMAIL, "reset", "a" * 43)
    relay.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp = relay.return_value.__enter__.return_value
    assert [call[0] for call in smtp.method_calls] == ["starttls", "send_message"]
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == EMAIL
    assert "https://tracegrid.example.com/reset-password#token=" in message.get_content()
