
import asyncio
import json
import logging
from time import time

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app.config import settings
from app.database import engine, get_db, initialize_schema
from app.routes.endpoints import router as endpoint_router
from app.routes.users import router as user_router
from app.routes.monitoring import router as monitoring_router
from app.routes.incidents import router as incident_router
from app.routes.analytics import router as analytics_router
from app.services.monitoring_events import PostgresEventListener
from app.services.incident_notifications import IncidentNotificationWorker
from app.services.scheduler import start_scheduler, scheduler
from app.services.websocket_manager import websocket_manager
from app.services.websocket_auth import authenticate_websocket, websocket_token_revoked
from app.services.connection_limits import socket_capacity
from app.services.http_security import MAX_WEBSOCKET_MESSAGE_BYTES, RequestBodyLimit, SecurityHeaders
from app.services.rate_limits import client_network, enforce_limits
from app.security import MAX_ACCESS_TOKEN_LENGTH


initialize_schema(engine)
WEBSOCKET_IDLE_SECONDS = 30

app = FastAPI(
    title="TraceGrid",
    description="API Monitoring & Analytics Platform",
    version="1.0.0",
    debug=False,
)


app.add_middleware(RequestBodyLimit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Retry-After"],
)
app.add_middleware(SecurityHeaders)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, error):
    return JSONResponse(status_code=422, content={"detail": [
        {key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()
    ]})


@app.exception_handler(SQLAlchemyError)
async def safe_database_error(request, error):
    logging.getLogger(__name__).warning("TraceGrid database operation failed")
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable."})


app.include_router(
    endpoint_router,
    prefix="/endpoints",
    tags=["Endpoints"]
)

app.include_router(
    user_router,
    prefix="/users",
    tags=["Users"]
)

app.include_router(
    monitoring_router,
    prefix="/monitor",
    tags=["Monitoring"]
)

app.include_router(incident_router, prefix="/incidents", tags=["Incidents"])
app.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])


@app.get("/")
def home():
    return {
        "project": "TraceGrid",
        "message": "Welcome to TraceGrid API Monitoring Platform",
        "status": "Running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "TraceGrid"
    }


@app.websocket("/ws/monitoring")
async def monitoring_websocket(websocket: WebSocket, db: Session = Depends(get_db)):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.FRONTEND_ORIGINS:
        await websocket.close(code=1008)
        return

    network = client_network(websocket.client)
    with socket_capacity.peer(network) as admitted:
        if not admitted:
            await websocket.close(code=1013)
            return
        try:
            await asyncio.to_thread(enforce_limits, db, ("socket_global", "all"), ("socket_ip", network))
        except HTTPException:
            await websocket.close(code=1013)
            return
        except SQLAlchemyError:
            await websocket.close(code=1011)
            return
        finally:
            db.close()
        await _authenticate_socket(websocket, db)


async def _authenticate_socket(websocket, db):
    await websocket.accept()
    try:
        try:
            frame = await asyncio.wait_for(websocket.receive(), timeout=5)
            if frame["type"] == "websocket.disconnect":
                return
            raw = frame.get("text")
            size = len(raw.encode("utf-8")) if raw is not None else len(frame.get("bytes") or b"")
            if size > MAX_WEBSOCKET_MESSAGE_BYTES:
                await websocket.close(code=1009)
                return
            message = json.loads(raw) if raw is not None else None
        except (ValueError, TimeoutError, RecursionError):
            message = None
        token = message.get("token") if isinstance(message, dict) and message.get("type") == "authenticate" else None
        if not isinstance(token, str) or not 0 < len(token) <= MAX_ACCESS_TOKEN_LENGTH:
            await websocket.close(code=4401)
            return
        identity = await asyncio.to_thread(authenticate_websocket, token, db)
        if identity is None:
            await websocket.close(code=4401)
            return

        with socket_capacity.owner(identity.user_id) as admitted:
            if not admitted:
                await websocket.close(code=1013)
                return
            try:
                await asyncio.to_thread(enforce_limits, db, ("socket_owner", str(identity.user_id)))
            except HTTPException:
                await websocket.close(code=1013)
                return
            finally:
                db.close()
            with websocket_manager.subscribe(identity) as subscription:
                # Recheck after subscribing so a concurrent logout cannot be missed during setup.
                if await asyncio.to_thread(websocket_token_revoked, token, db) or subscription.revoked:
                    await websocket.close(code=4401)
                    return
                await _stream_monitoring(websocket, subscription, token, db)
    except WebSocketDisconnect:
        return
    except SQLAlchemyError:
        await websocket.close(code=1011)


async def _stream_monitoring(websocket, subscription, token, db):
    expires_at = subscription.identity.expires_at
    if expires_at <= time():
        await websocket.close(code=4401)
        return

    incoming = asyncio.create_task(websocket.receive())
    update = asyncio.create_task(subscription.updates.get())
    try:
        await asyncio.wait_for(websocket.send_json({"type": "monitoring.ready"}), timeout=5)
        while not subscription.revoked and time() < expires_at:
            done, _ = await asyncio.wait(
                {incoming, update}, timeout=min(WEBSOCKET_IDLE_SECONDS, max(0, expires_at - time())),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if incoming in done:
                frame = incoming.result()
                if frame["type"] != "websocket.disconnect":
                    size = len((frame.get("text") or "").encode()) + len(frame.get("bytes") or b"")
                    await websocket.close(code=1009 if size > MAX_WEBSOCKET_MESSAGE_BYTES else 1008)
                return
            if time() >= expires_at or subscription.revoked:
                break
            if await asyncio.to_thread(websocket_token_revoked, token, db) or subscription.revoked or time() >= expires_at:
                break
            if update in done:
                await asyncio.wait_for(websocket.send_json(update.result()), timeout=min(5, expires_at - time()))
                update = asyncio.create_task(subscription.updates.get())
            else:
                listener = getattr(app.state, "event_listener", None)
                if listener is None or listener.connected.is_set():
                    await asyncio.wait_for(websocket.send_json({"type": "monitoring.heartbeat"}),
                                           timeout=min(5, expires_at - time()))
        await websocket.close(code=4401)
    except TimeoutError:
        await websocket.close(code=4401 if time() >= expires_at else 1011)
    finally:
        incoming.cancel()
        update.cancel()
        await asyncio.gather(incoming, update, return_exceptions=True)


@app.on_event("startup")
def start_monitoring():
    websocket_manager.set_event_loop(
        asyncio.get_running_loop()
    )

    app.state.event_listener = None
    if engine.dialect.name == "postgresql":
        app.state.event_listener = PostgresEventListener(engine, websocket_manager.publish_local)
        app.state.event_listener.start()
        if getattr(app.state, "incident_notification_worker", None) is None:
            app.state.incident_notification_worker = IncidentNotificationWorker(engine)
            app.state.incident_notification_worker.start()
    start_scheduler()
    print("TraceGrid automatic monitoring started")


@app.on_event("shutdown")
def stop_monitoring():
    try:
        scheduler.shutdown()
    finally:
        worker = getattr(app.state, "incident_notification_worker", None)
        if worker is not None:
            worker.stop()
            if not worker.thread.is_alive():
                app.state.incident_notification_worker = None
        listener = getattr(app.state, "event_listener", None)
        if listener is not None:
            listener.stop()
        websocket_manager.set_event_loop(None)
    print("TraceGrid automatic monitoring stopped")
