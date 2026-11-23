import asyncio
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.services.websocket_auth import WebSocketIdentity


@dataclass(eq=False)
class Subscription:
    identity: WebSocketIdentity
    updates: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    revoked: bool = False

    def notify(self, message: dict):
        # A resync preserves every invalidation when different updates share this bounded queue.
        if self.updates.full():
            if self.updates.get_nowait() != message:
                message = {"type": "monitoring.resync"}
        self.updates.put_nowait(message)


class WebSocketManager:
    def __init__(self):
        self._connections = defaultdict(set)
        self._loop = None

    def set_event_loop(self, loop):
        self._loop = loop

    @contextmanager
    def subscribe(self, identity):
        subscription = Subscription(identity)
        connections = self._connections[identity.user_id]
        connections.add(subscription)
        try:
            yield subscription
        finally:
            connections.discard(subscription)
            if not connections:
                self._connections.pop(identity.user_id, None)

    def _dispatch(self, event):
        event_type = event.get("type")
        if event_type == "monitoring.resync":
            for connections in self._connections.values():
                for subscription in connections:
                    subscription.notify({"type": event_type})
            return

        user_id = event.get("user_id")
        if type(user_id) is not int:
            return
        for subscription in self._connections.get(user_id, ()):
            if event_type in ("monitoring.updated", "endpoint.updated") and type(event.get("endpoint_id")) is int:
                subscription.notify({"type": event_type, "endpoint_id": event["endpoint_id"]})
            elif (event_type == "incident.updated" and type(event.get("incident_id")) is int
                  and event.get("action") in ("created", "acknowledged", "resolved")):
                subscription.notify({"type": event_type, "incident_id": event["incident_id"],
                                     "endpoint_id": event.get("endpoint_id"), "action": event["action"]})
            elif event_type == "session.revoked" and subscription.identity.token_digest == event.get("token_digest"):
                subscription.revoked = True
                subscription.notify({"type": event_type})
            elif (event_type == "session.reset" and type(event.get("session_version")) is int
                  and subscription.identity.session_version < event["session_version"]):
                subscription.revoked = True
                subscription.notify({"type": event_type})

    def publish_local(self, event):
        loop = self._loop
        if event is not None and loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._dispatch, event)
            except RuntimeError:
                # The event loop can close between the check and scheduling the callback.
                pass


websocket_manager = WebSocketManager()
