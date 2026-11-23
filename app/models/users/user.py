from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text, false
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    email_key = Column(Text, index=True)
    email_verification_required = Column(Boolean, nullable=False, server_default=false())
    email_verified_at = Column(DateTime(timezone=True))
    notify_incident_opened = Column(Boolean, nullable=False, server_default=false())
    notify_incident_recovered = Column(Boolean, nullable=False, server_default=false())
    session_version = Column(Integer, nullable=False, server_default="0")
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
