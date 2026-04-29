"""管理后台 API。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app import configs as configs_module
from app.admin.auth import login as admin_login_service
from app.audit import write as audit_write
from app.auth.security import hash_password
from app.billing.ledger import grant as billing_grant
from app.deps import get_current_admin, get_db
from app.http_utils import client_ip as _client_ip
from app.models.admin import Admin
from app.models.balance_ledger import BalanceLedger
from app.models.config_kv import ConfigKV
from app.models.user import User
from app.schemas.admin import (
    AdminAuthOut,
    AdminLedgerItemOut,
    AdminLoginIn,
    AdminOut,
    AdminUserDetailOut,
    AdminUserListOut,
    AdminUserOut,
    GrantIn,
    ResetPasswordIn,
    UpdateUserIn,
)
from app.schemas.config import ConfigItemOut, ConfigPutIn


router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------- auth/login ----------------

@router.post("/auth/login", response_model=AdminAuthOut)
def admin_login(payload: AdminLoginIn, db: Session = Depends(get_db)) -> AdminAuthOut:
    token, admin = admin_login_service(db, payload.username, payload.password)
    return AdminAuthOut(token=token, admin=AdminOut.model_validate(admin))


# ---------------- users list ----------------

@router.get("/users", response_model=AdminUserListOut)
def list_users(
    q: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUserListOut:
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.username.like(like)) | (User.phone.like(like)))
    total = query.count()
    rows = query.order_by(User.id.desc()).offset((page - 1) * size).limit(size).all()
    return AdminUserListOut(
        items=[AdminUserOut.model_validate(u) for u in rows],
        total=total,
        page=page,
        size=size,
    )


# ---------------- user detail ----------------

@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
def user_detail(
    user_id: int,
    _: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUserDetailOut:
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}},
        )
    recent = (
        db.query(BalanceLedger)
        .filter(BalanceLedger.user_id == user.id)
        .order_by(BalanceLedger.created_at.desc(), BalanceLedger.id.desc())
        .limit(20)
        .all()
    )
    return AdminUserDetailOut(
        user=AdminUserOut.model_validate(user),
        recent_ledger=[AdminLedgerItemOut.model_validate(r) for r in recent],
        recent_sessions=[],
    )


# ---------------- patch user ----------------

@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(
    user_id: int,
    payload: UpdateUserIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}},
        )
    changes: dict = {}
    if payload.status is not None and payload.status != user.status:
        changes["status"] = {"from": user.status, "to": payload.status}
        user.status = payload.status

    if changes:
        audit_write(
            db,
            admin_id=admin.id,
            action="patch_user",
            target_type="user",
            target_id=user.id,
            payload=changes,
            ip=_client_ip(request),
        )
        db.commit()
        db.refresh(user)
    return AdminUserOut.model_validate(user)


# ---------------- grant balance ----------------

@router.post("/users/{user_id}/grant", response_model=AdminUserOut)
def grant_balance(
    user_id: int,
    payload: GrantIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    if payload.delta_seconds == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INVALID_DELTA", "message": "变更秒数不能为 0"}},
        )
    reason = "admin_grant" if payload.delta_seconds > 0 else "admin_revoke"
    new_balance = billing_grant(
        db,
        user_id=user_id,
        delta_seconds=payload.delta_seconds,
        reason=reason,
        ref_type="admin",
        ref_id=admin.id,
        note=payload.note,
    )
    audit_write(
        db,
        admin_id=admin.id,
        action="grant_balance",
        target_type="user",
        target_id=user_id,
        payload={"delta_seconds": payload.delta_seconds, "new_balance": new_balance},
        ip=_client_ip(request),
        note=payload.note,
    )
    db.commit()
    user = db.query(User).filter(User.id == user_id).one()
    return AdminUserOut.model_validate(user)


# ---------------- reset password ----------------

@router.post("/users/{user_id}/reset-password", response_model=AdminUserOut)
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}},
        )
    user.password_hash = hash_password(payload.new_password)
    audit_write(
        db,
        admin_id=admin.id,
        action="reset_password",
        target_type="user",
        target_id=user.id,
        payload={},  # 不记新密码
        ip=_client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(user)


# ---------------- configs ----------------

@router.get("/configs", response_model=list[ConfigItemOut])
def list_configs(
    _: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[ConfigItemOut]:
    rows = db.query(ConfigKV).order_by(ConfigKV.key.asc()).all()
    return [ConfigItemOut(key=r.key, value=r.value) for r in rows]


@router.put("/configs/{key}", response_model=ConfigItemOut)
def put_config(
    key: str,
    payload: ConfigPutIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConfigItemOut:
    row = configs_module.save(db, key, payload.value)
    audit_write(
        db,
        admin_id=admin.id,
        action="update_config",
        target_type="config",
        target_id=key,
        payload={"value": payload.value},
        ip=_client_ip(request),
    )
    db.commit()
    return ConfigItemOut(key=row.key, value=row.value)
