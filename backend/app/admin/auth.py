"""Admin login service: verify credentials, issue admin JWT."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.security import make_admin_token, verify_password
from app.models.admin import Admin


def login(db: Session, username: str, password: str) -> tuple[str, Admin]:
    """Verify admin username/password. Returns (token, Admin) on success.

    Raises HTTPException(401, AUTH_INVALID) when credentials are wrong.
    """
    admin = db.query(Admin).filter(Admin.username == username).one_or_none()
    if admin is None or not verify_password(password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH_INVALID", "message": "用户名或密码错误"}},
        )
    return make_admin_token(admin.id), admin
