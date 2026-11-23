from datetime import timezone
from email.message import EmailMessage
from html import escape
import re
from urllib.parse import urlsplit

from email_validator import validate_email

from app.config import settings


FAILURE_LABELS = {
    "availability_failure": "Unsuccessful availability check",
    "http_error": "Unsuccessful HTTP response",
    "redirect": "Unexpected HTTP redirect",
    "dns_resolution": "Endpoint hostname could not be found",
    "tls_verification": "Endpoint certificate verification failed",
    "tls_error": "Endpoint TLS handshake failed",
    "timeout": "Endpoint did not respond in time",
    "connection": "Could not connect to the endpoint",
    "http_protocol": "Invalid HTTP response",
}


def safe_endpoint_origin(url):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode("ascii")
        port = parts.port
    except (UnicodeError, ValueError):
        return None
    if parts.scheme not in {"http", "https"} or not host:
        return None
    if ":" in host and re.fullmatch(r"[0-9a-fA-F:.]+", host):
        host = f"[{host}]"
    elif not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
        return None
    return f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def clean_label(value):
    return " ".join("".join(char for char in value if char.isprintable()).split())


def duration(started, ended):
    seconds = max(0, int((utc(ended) - utc(started)).total_seconds()))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return " ".join(
        ([f"{hours} h"] if hours else []) + ([f"{minutes} min"] if minutes else []) + [f"{seconds} s"]
    )


def incident_message(job, incident, recipient):
    opened = job.kind == "opened"
    title = "Incident opened" if opened else "Endpoint recovered"
    occurred_at = incident.detected_at if opened else incident.resolved_at
    details = [
        ("Endpoint", clean_label(incident.endpoint_name)),
        ("Status", "Open" if opened else "Resolved automatically"),
        ("Severity", incident.severity.capitalize()),
        ("Failure reason", FAILURE_LABELS.get(incident.failure_reason, "Unsuccessful availability check")),
        ("Detected" if opened else "Recovered", utc(occurred_at).strftime("%Y-%m-%d %H:%M:%S UTC")),
    ]
    if job.endpoint_origin:
        details.insert(1, ("Endpoint origin", job.endpoint_origin))
    if incident.failure_http_status is not None:
        details.append(("Failure HTTP status", str(incident.failure_http_status)))
    if not opened:
        if incident.recovery_http_status is not None:
            details.append(("Recovery HTTP status", str(incident.recovery_http_status)))
        details.append(("Duration", duration(incident.started_at, incident.resolved_at)))

    link = f"{str(settings.ACCOUNT_LINK_BASE_URL).rstrip('/')}/incidents?incident={incident.id}"
    message = EmailMessage()
    message["To"] = validate_email(recipient, check_deliverability=False).normalized
    message["Subject"] = f"TraceGrid | {title}"
    timestamp = int(utc(job.created_at).timestamp() * 1_000_000)
    message["Message-ID"] = f"<incident-{job.id}-{timestamp}@notifications.tracegrid>"
    plain = "\n".join(f"{label}: {value}" for label, value in details)
    message.set_content(f"{title}\n\n{plain}\n\nView incident: {link}\n")
    rows = "".join(
        '<tr><th scope="row" style="text-align:left;padding:8px;color:#515151;vertical-align:top">'
        f'{escape(label)}</th><td style="padding:8px;overflow-wrap:anywhere">{escape(value)}</td></tr>'
        for label, value in details
    )
    message.add_alternative(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<body style="margin:0;background:#f3f3f3;color:#171717;font:15px Arial,sans-serif">'
        '<main style="max-width:580px;margin:0 auto;background:#fff;padding:24px">'
        '<p style="font-size:14px;font-weight:bold;color:#454545">TraceGrid</p>'
        f'<h1 style="font-size:27px">{escape(title)}</h1>'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table>'
        '<p style="margin-top:24px"><a style="color:#171717;font-weight:bold" '
        f'href="{escape(link, quote=True)}">View incident</a></p></main></body></html>',
        subtype="html",
    )
    return message
