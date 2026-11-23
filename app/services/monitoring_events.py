import json
import logging
import select
from collections.abc import Callable
from threading import Event, Thread

from sqlalchemy import text


_CHANNEL = "tracegrid_monitoring_events"
logger = logging.getLogger(__name__)


def stage_event(db, event):
    if db.get_bind().dialect.name == "postgresql":
        # PostgreSQL delivers notifications only after this transaction commits.
        db.execute(text("SELECT pg_notify(:channel, :payload)"), {
            "channel": _CHANNEL, "payload": json.dumps(event),
        })
        return None
    return event


def stage_monitoring_update(db, endpoint):
    if endpoint.user_id is None:
        return None
    return stage_event(db, {
        "type": "monitoring.updated", "user_id": endpoint.user_id, "endpoint_id": endpoint.id,
    })


class PostgresEventListener:
    def __init__(self, engine, deliver: Callable[[dict], None]):
        self._engine = engine
        self._deliver = deliver
        self._stop = Event()
        self.connected = Event()
        self._thread = Thread(target=self._listen, name="tracegrid-notifications", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _listen(self):
        while not self._stop.is_set():
            try:
                with self._engine.connect() as connection:
                    connection.execution_options(isolation_level="AUTOCOMMIT")
                    driver = connection.connection.driver_connection
                    connection.detach()
                    connection.exec_driver_sql(f"LISTEN {_CHANNEL}")
                    self.connected.set()
                    self._deliver({"type": "monitoring.resync"})
                    while not self._stop.is_set():
                        if not select.select([driver], [], [], 1)[0]:
                            continue
                        driver.poll()
                        notifications = driver.notifies[:]
                        del driver.notifies[:]
                        for notice in notifications:
                            try:
                                event = json.loads(notice.payload)
                            except ValueError:
                                continue
                            if isinstance(event, dict):
                                self._deliver(event)
            except Exception:
                self.connected.clear()
                if not self._stop.is_set():
                    logger.warning("PostgreSQL monitoring event listener disconnected; retrying")
                    self._stop.wait(1)
            finally:
                self.connected.clear()
