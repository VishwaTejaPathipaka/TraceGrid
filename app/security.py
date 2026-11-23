import jwt
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from contextlib import contextmanager
from threading import BoundedSemaphore
from uuid import uuid4
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jwt.exceptions import InvalidTokenError

from app.config import settings
from app.database import get_db
from app.models.users import User
from app.models.token import RevokedToken

password_hash = PasswordHash.recommended()
MAX_ACCESS_TOKEN_LENGTH = 4096
_dummy_hash = password_hash.hash(uuid4().hex)
_hash_slots = BoundedSemaphore(settings.PASSWORD_HASH_SLOTS_PER_WORKER)

security = HTTPBearer()


@contextmanager
def _password_slot():
    if not _hash_slots.acquire(blocking=False):
        raise HTTPException(429, "Account requests are busy. Try again shortly.", headers={"Retry-After": "2"})
    try:
        yield
    finally:
        _hash_slots.release()


def hash_password(password: str) -> str:
    with _password_slot():
        return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    with _password_slot():
        try:
            return password_hash.verify(password, hashed_password)
        except UnknownHashError:
            password_hash.verify(password, _dummy_hash)
            return False


def verify_login_password(password, user):
    valid = verify_password(password, user.hashed_password if user is not None else _dummy_hash)
    return user is not None and valid


def create_access_token(data: dict):
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    to_encode.update({"exp": expire, "jti": uuid4().hex})

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    user, _ = authenticate_access_token(credentials.credentials, db)
    return user


def is_token_revoked(token: str, db: Session) -> bool:
    candidates = [revocation_key(token)]
    if len(token) <= 500:
        candidates.append(token)  # Preserve revocations created before digest storage.
    return db.query(RevokedToken.id).filter(RevokedToken.token.in_(candidates)).first() is not None


def revocation_key(token: str) -> str:
    return "sha256:" + sha256(token.encode()).hexdigest()


def authenticate_access_token(token: str, db: Session):
    invalid = HTTPException(401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    if not 0 < len(token) <= MAX_ACCESS_TOKEN_LENGTH:
        raise invalid
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub"]},
        )

    except (InvalidTokenError, TypeError, ValueError, OverflowError):
        raise invalid from None
    username = payload.get("sub")
    version = payload.get("session_version", 0)
    if (not isinstance(username, str) or not 0 < len(username) <= 50 or type(payload.get("exp")) is not int
            or type(version) is not int or version < 0 or is_token_revoked(token, db)):
        raise invalid
    user = db.query(User).filter(User.username == username).first()
    if user is None or user.email_verification_required or version != user.session_version:
        raise invalid

    return user, payload
