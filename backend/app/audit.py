"""管理员操作审计日志写入工具。"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog


def write(
    db: Session,
    *,
    admin_id: int,
    action: str,
    target_type: str,
    target_id: Any,
    payload: Optional[dict] = None,
    ip: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Append an audit entry. Caller is responsible for db.commit()
    (typically the calling endpoint's transaction)."""
    entry = AdminAuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        payload=payload or {},
        ip=ip,
        note=note,
    )
    db.add(entry)
