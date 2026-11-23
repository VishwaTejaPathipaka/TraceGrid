from collections import Counter
from contextlib import contextmanager
from threading import Lock

from sqlalchemy import text

from app.config import settings
from app.services.rate_limits import reject


_MANUAL_USER_LOCK = 1414679213
_MANUAL_SLOT_LOCK = 1414679214
_local_manual_lock = Lock()
_local_manual_owners = set()


def try_lock(connection, namespace, key):
    return connection.scalar(text("SELECT pg_try_advisory_lock(:namespace, :key)"),
                             {"namespace": namespace, "key": key})


@contextmanager
def manual_probe_slot(engine, owner_id):
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            try:
                with connection.begin():
                    owner_locked = try_lock(connection, _MANUAL_USER_LOCK, owner_id)
                    admitted = owner_locked and any(
                        try_lock(connection, _MANUAL_SLOT_LOCK, slot) for slot in range(settings.MANUAL_PROBE_SLOTS)
                    )
            except Exception:
                connection.invalidate()
                raise
            if owner_locked:
                # An admitted probe frees its pool slot, and closing releases even a partial lock.
                connection.detach()
            if not admitted:
                raise reject(10)
            yield
        return

    with _local_manual_lock:
        if owner_id in _local_manual_owners or len(_local_manual_owners) >= settings.MANUAL_PROBE_SLOTS:
            raise reject(10)
        _local_manual_owners.add(owner_id)
    try:
        yield
    finally:
        with _local_manual_lock:
            _local_manual_owners.remove(owner_id)


class WebSocketCapacity:
    """Per-ASGI-worker socket quotas, including connections still authenticating."""

    def __init__(self):
        self.total = 0
        self.peers = Counter()
        self.owners = Counter()

    @contextmanager
    def peer(self, network):
        if self.total >= settings.MAX_WEBSOCKETS_PER_WORKER or self.peers[network] >= settings.MAX_WEBSOCKETS_PER_IP:
            yield False
            return
        self.total += 1
        self.peers[network] += 1
        try:
            yield True
        finally:
            self.total -= 1
            self._release(self.peers, network)

    @contextmanager
    def owner(self, owner_id):
        if self.owners[owner_id] >= settings.MAX_WEBSOCKETS_PER_USER:
            yield False
            return
        self.owners[owner_id] += 1
        try:
            yield True
        finally:
            self._release(self.owners, owner_id)

    @staticmethod
    def _release(counts, identity):
        counts[identity] -= 1
        if not counts[identity]:
            del counts[identity]


socket_capacity = WebSocketCapacity()
