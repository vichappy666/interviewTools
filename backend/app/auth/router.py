"""Auth endpoints: /api/auth/register, /login, /reset-password."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import service, throttle
from app.auth.security import make_user_token
from app.deps import get_db
from app.http_utils import client_ip as _client_ip
from app.schemas.auth import AuthOut, LoginIn, RegisterIn, ResetPasswordIn, UserOut


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthOut)
def register_endpoint(payload: RegisterIn, db: Session = Depends(get_db)) -> AuthOut:
    user = service.register(db, payload)
    return AuthOut(token=make_user_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
def login_endpoint(
    payload: LoginIn, request: Request, db: Session = Depends(get_db)
) -> AuthOut:
    # 5 attempts / 60s, both on username and on IP.
    throttle.consume(db, scope=f"login:user:{payload.username}", limit=5, window_seconds=60)
    throttle.consume(db, scope=f"login:ip:{_client_ip(request)}", limit=20, window_seconds=60)
    user = service.login(db, payload)
    return AuthOut(token=make_user_token(user.id), user=UserOut.model_validate(user))


@router.post("/reset-password", response_model=UserOut)
def reset_password_endpoint(
    payload: ResetPasswordIn, request: Request, db: Session = Depends(get_db)
) -> UserOut:
    throttle.consume(db, scope=f"reset:user:{payload.username}", limit=3, window_seconds=300)
    throttle.consume(db, scope=f"reset:ip:{_client_ip(request)}", limit=10, window_seconds=300)
    user = service.reset_password(db, payload)
    return UserOut.model_validate(user)
