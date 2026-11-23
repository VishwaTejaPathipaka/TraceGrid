import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from conftest import fail_probe_commit, verify_test_account
from fastapi import WebSocketDisconnect
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.security import create_access_token
from app.services import scheduler
from app.services.monitoring_events import PostgresEventListener
from app.services.monitoring_policy import MonitoringPolicyError
from app.services.websocket_auth import WebSocketIdentity
from app.services.websocket_manager import WebSocketManager, websocket_manager


RESULT = {"status": "UP", "status_code": 200, "response_time": 6.0}


def login(client, username):
    response = client.post("/users/login", json={"username": username, "password": "TestPass@123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def account(client, username, *, endpoint=True):
    response = client.post("/users/register", json={
        "username": username, "email": f"{username}@example.com", "password": "TestPass@123",
    })
    assert response.status_code == 202
    verify_test_account(client, f"{username}@example.com")
    token = login(client, username)
    if not endpoint:
        return token
    response = client.post("/endpoints/", headers=bearer(token), json={
        "name": f"{username} endpoint", "url": "https://jsonplaceholder.typicode.com/",
    })
    assert response.status_code == 200
    return token, response.json()["id"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def connected(client, token):
    def connection_count():
        return sum(map(len, websocket_manager._connections.values()))

    async def wait_for_disconnect(previous_count):
        async with asyncio.timeout(3):
            while connection_count() > previous_count:
                await asyncio.sleep(0.01)

    previous_count = client.portal.call(connection_count)
    with client.websocket_connect("/ws/monitoring", headers={"Origin": "http://localhost:5173"}) as socket:
        socket.send_json({"type": "authenticate", "token": token})
        assert socket.receive_json() == {"type": "monitoring.ready"}
        try:
            yield socket
        finally:
            socket.close()
            # Let the ASGI handler release its subscription before TestClient cancels it.
            client.portal.call(wait_for_disconnect, previous_count)


def token_lifetime(monkeypatch, username, seconds):
    class Clock:
        @staticmethod
        def now(_):
            return datetime.now(timezone.utc) - timedelta(minutes=30) + timedelta(seconds=seconds)

    with monkeypatch.context() as patched:
        patched.setattr("app.security.datetime", Clock)
        return create_access_token({"sub": username})


def test_rejects_untrusted_origin(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/monitoring", headers={"Origin": "https://untrusted.example"}):
            pass
    assert closed.value.code == 1008


def test_authenticated_idle_socket_delivers_health_heartbeat(client, monkeypatch):
    token = account(client, "idle_heartbeat_fixture", endpoint=False)
    monkeypatch.setattr("app.main.WEBSOCKET_IDLE_SECONDS", .05)
    with connected(client, token) as socket:
        assert socket.receive_json() == {"type": "monitoring.heartbeat"}


def test_mixed_bounded_queue_preserves_every_invalidation():
    manager = WebSocketManager()
    identity = WebSocketIdentity(1, 100, "fixture")
    with manager.subscribe(identity) as subscription:
        manager._dispatch({"type": "incident.updated", "user_id": 1, "incident_id": 9,
                           "endpoint_id": 2, "action": "created"})
        manager._dispatch({"type": "monitoring.updated", "user_id": 1, "endpoint_id": 3})
        assert subscription.updates.qsize() == 1
        assert subscription.updates.get_nowait() == {"type": "monitoring.resync"}
        manager._dispatch({"type": "endpoint.updated", "user_id": 2, "endpoint_id": 4})
        assert subscription.updates.empty()


@pytest.mark.parametrize("kind", ["missing", "malformed", "expired", "revoked"])
def test_requires_an_active_access_token(client, monkeypatch, kind):
    token = account(client, "auth_socket", endpoint=False)
    if kind == "expired":
        token = token_lifetime(monkeypatch, "auth_socket", -30)
    elif kind == "revoked":
        assert client.post("/users/logout", headers=bearer(token)).status_code == 200
    elif kind == "malformed":
        token = "invalid-token"
    else:
        token = None

    with client.websocket_connect("/ws/monitoring") as socket:
        socket.send_json({"type": "authenticate", "token": token})
        assert socket.receive()["code"] == 4401


def test_closes_an_idle_socket_at_token_expiry(client, monkeypatch):
    account(client, "expiry_socket", endpoint=False)
    token = token_lifetime(monkeypatch, "expiry_socket", 2)

    with connected(client, token) as socket:
        assert socket.receive()["code"] == 4401


def test_logout_closes_only_sockets_using_the_revoked_token(client, monkeypatch):
    token, endpoint_id = account(client, "logout_socket")
    other_session = login(client, "logout_socket")
    assert other_session != token
    monkeypatch.setattr("app.routes.monitoring.check_api", Mock(return_value=RESULT))

    with connected(client, token) as revoked, connected(client, other_session) as active:
        assert client.post("/users/logout", headers=bearer(token)).status_code == 200
        assert revoked.receive()["code"] == 4401
        assert client.get(f"/monitor/{endpoint_id}/check", headers=bearer(other_session)).status_code == 200
        assert active.receive_json() == {"type": "monitoring.updated", "endpoint_id": endpoint_id}


def test_persisted_probes_refresh_owner_data_and_support_reconnect(client, monkeypatch):
    token, endpoint_id = account(client, "owner_socket")
    other_token, other_id = account(client, "other_socket")
    monkeypatch.setattr("app.routes.monitoring.check_api", Mock(return_value=RESULT))
    headers = bearer(token)

    with connected(client, token) as owner, connected(client, other_token) as other:
        assert client.get(f"/monitor/{other_id}/check", headers=headers).status_code == 404
        assert client.get(f"/monitor/{endpoint_id}/check", headers=headers).status_code == 200
        assert owner.receive_json() == {"type": "monitoring.updated", "endpoint_id": endpoint_id}
        assert client.get(f"/monitor/{endpoint_id}/history", headers=headers).json()[0]["status"] == "UP"
        assert client.get("/endpoints/", headers=headers).json()[0]["latest_check"]["status"] == "UP"
        assert client.get("/monitor/dashboard/recent", headers=bearer(other_token)).json() == []
        assert client.get(f"/monitor/{other_id}/check", headers=bearer(other_token)).status_code == 200
        assert other.receive_json() == {"type": "monitoring.updated", "endpoint_id": other_id}

    with contextmanager(app.dependency_overrides[get_db])() as db:
        monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(scheduler, "check_api", Mock(return_value={**RESULT, "status": "DOWN", "status_code": 503}))

    with connected(client, token) as reconnected:
        scheduler.dispatch_due_check(0)
        scheduler.dispatch_due_check(0)
        assert reconnected.receive_json() == {"type": "monitoring.updated", "endpoint_id": endpoint_id}
        assert client.get("/endpoints/", headers=headers).json()[0]["latest_check"]["status_code"] == 503
        recent = client.get("/monitor/dashboard/recent", headers=headers).json()
        assert [row["endpoint_id"] for row in recent] == [endpoint_id, endpoint_id]

        monkeypatch.setattr(scheduler, "check_api", Mock(side_effect=MonitoringPolicyError("Use a public URL.")))
        future = scheduler._wall_time() + timedelta(seconds=31)
        monkeypatch.setattr(scheduler, "_wall_time", lambda: future)
        scheduler.dispatch_due_check(0)
        scheduler.dispatch_due_check(0)
        assert reconnected.receive_json() == {"type": "monitoring.updated", "endpoint_id": endpoint_id}
        assert client.get("/endpoints/", headers=headers).json()[0]["configuration_error"] == "Use a public URL."
        assert len(client.get(f"/monitor/{endpoint_id}/history", headers=headers).json()) == 2


def test_failed_manual_commit_does_not_publish(client, monkeypatch):
    token, endpoint_id = account(client, "failed_commit_socket")
    publish = Mock()
    monkeypatch.setattr(websocket_manager, "publish_local", publish)
    monkeypatch.setattr("app.routes.monitoring.check_api", Mock(return_value=RESULT))
    with monkeypatch.context() as patched:
        fail_probe_commit(patched)
        assert client.get(f"/monitor/{endpoint_id}/check", headers=bearer(token)).status_code == 503
    publish.assert_not_called()
    assert client.get(f"/monitor/{endpoint_id}/history", headers=bearer(token)).json() == []


def test_dispatch_isolates_users_and_sanitizes_event_payload():
    async def exercise():
        manager = WebSocketManager()
        manager.set_event_loop(asyncio.get_running_loop())
        with manager.subscribe(WebSocketIdentity(1, 1000, "first")) as first:
            with manager.subscribe(WebSocketIdentity(2, 1000, "second")) as second:
                manager.publish_local({"type": "monitoring.updated", "user_id": 1, "endpoint_id": 42})
                assert await asyncio.wait_for(first.updates.get(), 1) == {
                    "type": "monitoring.updated", "endpoint_id": 42,
                }
                assert second.updates.empty()
        assert not manager._connections

    asyncio.run(exercise())


def test_postgres_listener_retains_driver_when_detaching_from_pool(monkeypatch):
    event = {"type": "monitoring.updated", "user_id": 1, "endpoint_id": 4}
    driver = Mock(notifies=[SimpleNamespace(payload=json.dumps(event))])
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.connection.driver_connection = driver
    connection.detach.side_effect = lambda: setattr(connection.connection, "driver_connection", None)
    deliver = Mock()
    listener = PostgresEventListener(engine, deliver)

    def readable(*_):
        listener._stop.set()
        return [driver], [], []

    read_ready = Mock(side_effect=readable)
    monkeypatch.setattr("app.services.monitoring_events.select.select", read_ready)

    listener._listen()

    read_ready.assert_called_once_with([driver], [], [], 1)
    assert [call.args[0] for call in deliver.call_args_list] == [{"type": "monitoring.resync"}, event]
