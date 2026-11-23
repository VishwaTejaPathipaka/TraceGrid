import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from uuid import uuid4

from app.config import settings


logger = logging.getLogger(__name__)


def send_email(message):
    """Deliver a prepared message, leaving failure handling to the caller."""
    message["From"] = settings.EMAIL_FROM
    if settings.EMAIL_DELIVERY == "outbox":
        directory = settings.EMAIL_OUTBOX_DIR
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(directory / f"{uuid4().hex}.eml", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(message.as_bytes())
        return

    context = ssl.create_default_context()
    if settings.SMTP_TLS == "implicit":
        connection = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10, context=context)
    else:
        connection = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
    with connection as smtp:
        if settings.SMTP_TLS == "starttls":
            smtp.starttls(context=context)
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD.get_secret_value())
        smtp.send_message(message)


def deliver_account_email(recipient, purpose, token):
    base_url = str(settings.ACCOUNT_LINK_BASE_URL).rstrip("/")
    path = "verify-email" if purpose == "verify" else "reset-password"
    title = "Verify your email" if purpose == "verify" else "Reset your password"
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = f"{title} for TraceGrid"
    message.set_content(
        f"{title} using this single-use link:\n\n{base_url}/{path}#token={token}\n\n"
        "If you did not request this, you can ignore this message."
    )
    try:
        send_email(message)
    except (OSError, smtplib.SMTPException):
        logger.error("TraceGrid account email delivery failed")
