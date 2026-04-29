from sqlalchemy import BigInteger, Column, DateTime, Integer, String, func

from app.db import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
