from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import delete, select

from app.models.token import AccountToken
from app.models.users import User


VERIFY = "verify"
RESET = "reset"
LIFETIMES = {VERIFY: timedelta(hours=24), RESET: timedelta(minutes=30)}
RESEND_COOLDOWN = timedelta(minutes=1)


def digest_token(token):
    return sha256(token.encode("ascii")).hexdigest()


def issue_token(db, user_id, purpose):
    # Existing accounts are locked by the caller before issuing or consuming links.
    now = datetime.now(timezone.utc)
    record = db.get(AccountToken, (user_id, purpose))
    if record is not None:
        issued_at = record.issued_at
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if now - issued_at < RESEND_COOLDOWN:
            return None
    else:
        record = AccountToken(user_id=user_id, purpose=purpose)
        db.add(record)
    token = token_urlsafe(32)
    record.digest = digest_token(token)
    record.issued_at = now
    record.expires_at = now + LIFETIMES[purpose]
    return token


def consume_token(db, token, purpose):
    digest = digest_token(token)
    user_id = db.scalar(select(AccountToken.user_id).where(
        AccountToken.digest == digest, AccountToken.purpose == purpose,
    ))
    if user_id is None:
        return None
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        return None
    consumed = db.execute(delete(AccountToken).where(
        AccountToken.user_id == user.id, AccountToken.purpose == purpose, AccountToken.digest == digest,
        AccountToken.expires_at > datetime.now(timezone.utc),
    )).rowcount
    return user if consumed == 1 else None
