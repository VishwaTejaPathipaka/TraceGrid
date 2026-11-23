from hashlib import sha256
import hmac
from ipaddress import IPv6Address, ip_address, ip_network
from threading import Lock
from time import monotonic, time

from fastapi import HTTPException
from sqlalchemy import case, delete, extract, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import RATE_POLICIES, settings
from app.models.rate_limit import RateLimitCounter


_counter = RateLimitCounter.__table__
_cleanup_gate = Lock()
_next_cleanup = 0.0


def client_network(client):
    # The launcher uses the actual peer unless a specific trusted proxy has been configured.
    try:
        address = ip_address(client.host if client else "")
    except ValueError:
        return "unknown"
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ip_network((address, 64), strict=False))
    return str(address)


def conflict_insert(db, table):
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    return insert(table)


def reject(retry_after):
    return HTTPException(
        429, "Too many requests. Try again later.", headers={"Retry-After": str(max(1, retry_after))},
    )


def _clock(db):
    if db.get_bind().dialect.name == "postgresql":
        return int(db.scalar(select(extract("epoch", func.clock_timestamp()))))
    return int(time())


def _consume(db, policy, identity, now):
    default, seconds = RATE_POLICIES[policy]
    limit = settings.SECURITY_RATE_OVERRIDES.get(policy, default)
    expires = now - now % seconds + seconds
    key = hmac.new(settings.SECRET_KEY.encode(), f"rate-limit:{policy}:{identity}".encode(), sha256).hexdigest()
    expired = _counter.c.expires_at <= now
    insert = conflict_insert(db, _counter).values(key=key, expires_at=expires, hits=1)
    hits = db.scalar(insert.on_conflict_do_update(
        index_elements=[_counter.c.key],
        set_=dict(expires_at=case((expired, expires), else_=_counter.c.expires_at),
                  hits=case((expired, 1), else_=_counter.c.hits + 1)),
        where=or_(expired, _counter.c.hits < limit),
    ).returning(_counter.c.hits))
    return 0 if hits is not None else expires - now


def _prune(db, now):
    global _next_cleanup
    with _cleanup_gate:
        current = monotonic()
        if current < _next_cleanup:
            return
        _next_cleanup = current + 30
    if db.get_bind().dialect.name == "postgresql" and not db.scalar(
        text("SELECT pg_try_advisory_xact_lock(1414679212)")
    ):
        return
    expired = select(_counter.c.key).where(_counter.c.expires_at <= now).order_by(
        _counter.c.expires_at,
    ).limit(5000).with_for_update(skip_locked=True)
    db.execute(delete(_counter).where(_counter.c.key.in_(expired)))


def enforce_limits(db, *rules):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("SET LOCAL statement_timeout = '4s'"))
    now = _clock(db)
    # A denied request never spends capacity in the other scopes. Rules have a consistent lock order.
    for policy, identity in rules:
        wait = _consume(db, policy, identity, now)
        if wait:
            db.rollback()
            raise reject(wait)
    _prune(db, now)
    db.commit()


def limit_account_request(db, request, action, identifier=None):
    network = client_network(request.client)
    rules = [(f"{action}_global", "all"), (f"{action}_ip", network)]
    if identifier is not None:
        name = identifier.strip().casefold()
        rules.append((f"{action}_source_account", f"{network}/{name}"))
        if action == "login":
            rules.append(("login_account", name))
    enforce_limits(db, *rules)


def limit_owner(db, owner_id, operation):
    enforce_limits(db, (operation, str(owner_id)))
