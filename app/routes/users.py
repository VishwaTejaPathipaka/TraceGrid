from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.token import RevokedToken
from app.models.users import User
from app.schemas.user import (
    EmailRequest, NotificationPreferences, NotificationPreferencesUpdate, ResetPassword, UserCreate, UserLogin, VerifyEmail,
)
from app.security import create_access_token, get_current_user, hash_password, revocation_key, security, verify_login_password, verify_password
from app.services.account_email import deliver_account_email
from app.services.account_tokens import RESET, VERIFY, consume_token, issue_token
from app.services.monitoring_events import stage_event
from app.services.rate_limits import conflict_insert, limit_account_request
from app.services.websocket_auth import token_digest
from app.services.websocket_manager import websocket_manager

router = APIRouter()


VERIFY_RESPONSE = {"message": "If verification is available for this address, check your inbox for a link."}
RESET_RESPONSE = {"message": "If an account exists for this address, check your inbox for a reset link."}
INVALID_LINK = "This link is invalid or expired. Request a new link."


@router.post("/register", status_code=202)
def register_user(user: UserCreate, tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    limit_account_request(db, request, "register")
    email = user.email.lower()
    hashed_password = hash_password(user.password)
    existing_user = db.scalar(select(User.id).where(or_(User.username == user.username, User.email_key == email,
                                                     User.email == email)).limit(1))
    if existing_user is not None:
        return VERIFY_RESPONSE

    new_user = User(
        username=user.username, email=email, email_key=email,
        hashed_password=hashed_password, email_verification_required=True,
    )
    db.add(new_user)
    try:
        db.flush()
        token = issue_token(db, new_user.id, VERIFY)
        db.commit()
    except IntegrityError:
        # The existing unique email and username constraints also cover concurrent signups.
        db.rollback()
        return VERIFY_RESPONSE
    tasks.add_task(deliver_account_email, email, VERIFY, token)
    return VERIFY_RESPONSE


def request_link(db, tasks, email, purpose):
    users = db.scalars(select(User).where(User.email_key == email.lower()).limit(2).with_for_update()).all()
    # Multiple legacy rows can share a case-insensitive email. Avoid picking an account.
    if len(users) != 1:
        return
    user = users[0]
    if purpose == VERIFY and user.email_verified_at is not None:
        return
    recipient = user.email
    token = issue_token(db, user.id, purpose)
    db.commit()
    if token:
        tasks.add_task(deliver_account_email, recipient, purpose, token)


@router.post("/resend-verification", status_code=202)
def resend_verification(request: EmailRequest, tasks: BackgroundTasks, client: Request, db: Session = Depends(get_db)):
    limit_account_request(db, client, "mail", request.email)
    request_link(db, tasks, request.email, VERIFY)
    return VERIFY_RESPONSE


@router.post("/verify-email")
def verify_email(request: VerifyEmail, client: Request, db: Session = Depends(get_db)):
    limit_account_request(db, client, "reset")
    user = consume_token(db, request.token, VERIFY)
    if user is None or user.email_verified_at is not None:
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Enter the password you set for this account.")
    user.email_verification_required = False
    user.email_verified_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Email verified. You can now sign in."}


@router.get("/notification-preferences", response_model=NotificationPreferences)
def notification_preferences(user: User = Depends(get_current_user)):
    return NotificationPreferences(
        verified_email=user.email if user.email_verified_at is not None else None,
        incident_opened=user.notify_incident_opened,
        incident_recovered=user.notify_incident_recovered,
    )


@router.put("/notification-preferences", response_model=NotificationPreferences)
def update_notification_preferences(
    request: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user = db.get(User, user.id, with_for_update=True, populate_existing=True)
    if user.email_verified_at is None and (request.incident_opened or request.incident_recovered):
        raise HTTPException(409, "Verify your email before enabling incident notifications.")
    user.notify_incident_opened = request.incident_opened
    user.notify_incident_recovered = request.incident_recovered
    response = notification_preferences(user)
    db.commit()
    return response


@router.post("/forgot-password", status_code=202)
def forgot_password(request: EmailRequest, tasks: BackgroundTasks, client: Request, db: Session = Depends(get_db)):
    limit_account_request(db, client, "mail", request.email)
    request_link(db, tasks, request.email, RESET)
    return RESET_RESPONSE


@router.post("/reset-password")
def reset_password(request: ResetPassword, client: Request, db: Session = Depends(get_db)):
    limit_account_request(db, client, "reset")
    user = consume_token(db, request.token, RESET)
    if user is None:
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    user.hashed_password = hash_password(request.password)
    user.session_version += 1
    needs_verification = user.email_verification_required
    event = stage_event(db, {
        "type": "session.reset", "user_id": user.id, "session_version": user.session_version,
    })
    db.commit()
    websocket_manager.publish_local(event)
    if needs_verification:
        return {"message": "Password reset. Verify your email before signing in."}
    return {"message": "Password reset. Sign in with your new password."}


@router.post("/login")
def login_user(user: UserLogin, request: Request, db: Session = Depends(get_db)):
    limit_account_request(db, request, "login", user.username)

    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    if not verify_login_password(user.password, existing_user):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if existing_user.email_verification_required:
        raise HTTPException(status_code=403, detail="Verify your email before signing in.")

    access_token = create_access_token(
        data={"sub": existing_user.username, "session_version": existing_user.session_version}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
    
    
@router.post("/logout")
def logout_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    token = credentials.credentials

    revoked = RevokedToken.__table__
    inserted = db.execute(conflict_insert(db, revoked).values(token=revocation_key(token))
                          .on_conflict_do_nothing(index_elements=[revoked.c.token])).rowcount
    event = stage_event(db, {
        "type": "session.revoked", "user_id": current_user.id, "token_digest": token_digest(token),
    }) if inserted else None
    db.commit()
    websocket_manager.publish_local(event)

    return {"message": "Successfully logged out"}
