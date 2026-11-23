from sqlalchemy import BigInteger, Column, Index, Integer, String

from app.database import Base


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    key = Column(String(64), primary_key=True)
    expires_at = Column(BigInteger, nullable=False)
    hits = Column(Integer, nullable=False)

    __table_args__ = (Index("ix_rate_limit_counters_expiry", "expires_at"),)
