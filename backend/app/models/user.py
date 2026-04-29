from sqlalchemy import BigInteger, Column, DateTime, Integer, SmallInteger, String, func

from app.db import Base


class User(Base):
    __tablename__ = "users"

    # BigInteger on MySQL/Postgres; falls back to Integer on SQLite so that
    # AUTOINCREMENT works in tests.
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    phone = Column(String(32), nullable=True)
    balance_seconds = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(SmallInteger, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
