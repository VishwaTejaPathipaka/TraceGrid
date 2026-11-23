from dataclasses import dataclass
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.security import authenticate_access_token


@dataclass(frozen=True)
class WebSocketIdentity:
    user_id: int
    expires_at: int
    token_digest: str
    session_version: int = 0


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def authenticate_websocket(token: str, db: Session) -> WebSocketIdentity | None:
    try:
        user, claims = authenticate_access_token(token, db)
        return WebSocketIdentity(user.id, int(claims["exp"]), token_digest(token), user.session_version)
    except (HTTPException, ValueError, TypeError, OverflowError):
        return None
    finally:
        db.close()


def websocket_token_revoked(token: str, db: Session) -> bool:
    return authenticate_websocket(token, db) is None
