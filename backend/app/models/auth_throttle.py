from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from app.db import Base


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    scope = Column(String(80), unique=True, nullable=False)
    count = Column(Integer, nullable=False, default=0, server_default="0")
    reset_at = Column(DateTime(timezone=False), nullable=False)
