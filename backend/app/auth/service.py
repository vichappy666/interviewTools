"""Auth business logic: register / login / reset-password.

Each function returns the User on success, raises HTTPException with our
{error: {code, message}} envelope on failure.
"""
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginIn, RegisterIn, ResetPasswordIn


def _http_error(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"error": {"code": code, "message": message}},
    )


def register(db: Session, payload: RegisterIn) -> User:
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        phone=payload.phone,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _http_error("USERNAME_TAKEN", "用户名已被注册", status.HTTP_409_CONFLICT)
    db.refresh(user)
    return user


def login(db: Session, payload: LoginIn) -> User:
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise _http_error("AUTH_INVALID", "用户名或密码错误", status.HTTP_401_UNAUTHORIZED)
    if user.status != 1:
        raise _http_error("AUTH_INVALID", "账户已被封禁", status.HTTP_401_UNAUTHORIZED)
    return user


def reset_password(db: Session, payload: ResetPasswordIn) -> User:
    user = (
        db.query(User)
        .filter(User.username == payload.username, User.phone == payload.phone)
        .one_or_none()
    )
    if user is None:
        # Deliberately uniform: don't leak which field mismatched.
        raise _http_error(
            "RESET_NO_MATCH",
            "用户名或手机号不匹配",
            status.HTTP_400_BAD_REQUEST,
        )
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return user
