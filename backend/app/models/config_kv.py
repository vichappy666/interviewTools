"""configs 表 ORM 模型：key-value 配置存储。"""
from sqlalchemy import JSON, Column, DateTime, String, func

from app.db import Base


class ConfigKV(Base):
    __tablename__ = "configs"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
