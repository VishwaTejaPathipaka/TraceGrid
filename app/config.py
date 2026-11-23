from pathlib import Path
from ipaddress import ip_network
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


RATE_POLICIES = {
    "login_global": (600, 60), "login_ip": (90, 300), "login_source_account": (8, 300), "login_account": (40, 900),
    "register_global": (180, 60), "register_ip": (20, 3600),
    "mail_global": (240, 60), "mail_ip": (30, 900), "mail_source_account": (5, 900),
    "reset_global": (240, 60), "reset_ip": (30, 300),
    "socket_global": (900, 60), "socket_ip": (90, 60),
    "socket_owner": (30, 60), "endpoint_write": (20, 60), "manual_check": (12, 60),
    "analytics": (60, 60), "history": (60, 60),
}


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    FRONTEND_ORIGINS: list[str] = ["http://localhost:5173"]
    SCHEDULED_PROBE_WORKERS: int = Field(default=4, ge=1, le=32)
    SCHEDULED_PROBES_PER_OWNER: int = Field(default=2, ge=1, le=32)
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1)
    DATABASE_MAX_OVERFLOW: int = Field(default=10, ge=0)
    ACCOUNT_LINK_BASE_URL: AnyHttpUrl = "http://localhost:5173"
    EMAIL_DELIVERY: Literal["outbox", "smtp"] = "outbox"
    EMAIL_OUTBOX_DIR: Path = Path(".tracegrid-mail")
    EMAIL_FROM: EmailStr = "tracegrid@example.com"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_TLS: Literal["starttls", "implicit"] = "starttls"
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SECURITY_RATE_OVERRIDES: dict[str, Annotated[int, Field(ge=1, le=10000)]] = Field(default_factory=dict)
    MAX_ENDPOINTS_PER_USER: int = Field(default=50, ge=1, le=1000)
    MANUAL_PROBE_SLOTS: int = Field(default=4, ge=1, le=16)
    PASSWORD_HASH_SLOTS_PER_WORKER: int = Field(default=4, ge=1, le=16)
    MAX_REQUEST_BODY_BYTES: int = Field(default=16384, ge=1024, le=131072)
    MAX_WEBSOCKETS_PER_WORKER: int = Field(default=64, ge=1, le=512)
    MAX_WEBSOCKETS_PER_IP: int = Field(default=16, ge=1, le=128)
    MAX_WEBSOCKETS_PER_USER: int = Field(default=6, ge=1, le=48)
    TRUSTED_PROXY_NETWORKS: list[str] = Field(default_factory=list)
    ENABLE_HSTS: bool = False

    @model_validator(mode="after")
    def validate_security_settings(self):
        if self.SECURITY_RATE_OVERRIDES.keys() - RATE_POLICIES.keys():
            raise ValueError("Unknown security rate override")
        for origin in self.FRONTEND_ORIGINS:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None
                    or parsed.path or parsed.query or parsed.fragment or "*" in origin
                    or any(not char.isascii() or char.isspace() for char in origin)):
                raise ValueError("Frontend origins must be exact HTTP(S) origins without a trailing slash")
            # Validate the port while accepting explicit loopback development origins.
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("Invalid frontend origin port")
        for entry in self.TRUSTED_PROXY_NETWORKS:
            if ip_network(entry, strict=False).prefixlen == 0:
                raise ValueError("Trusted proxy networks cannot include all addresses")
        return self

    @model_validator(mode="after")
    def validate_email_settings(self):
        if any((self.ACCOUNT_LINK_BASE_URL.query, self.ACCOUNT_LINK_BASE_URL.fragment,
                self.ACCOUNT_LINK_BASE_URL.username, self.ACCOUNT_LINK_BASE_URL.password)):
            raise ValueError("Account link base URL must omit credentials, query and fragment")
        if self.EMAIL_DELIVERY == "smtp":
            if not self.SMTP_HOST or self.ACCOUNT_LINK_BASE_URL.scheme != "https":
                raise ValueError("SMTP requires a host and an HTTPS account link base URL")
            if bool(self.SMTP_USERNAME) != bool(self.SMTP_PASSWORD):
                raise ValueError("Configure both SMTP username and password or neither")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )


settings = Settings()
