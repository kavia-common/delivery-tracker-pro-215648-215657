from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from src.api.config import settings
from src.api.db import get_db
from src.api.models import User, UserRole
from src.api.schemas import UserOut

# Password hashing context
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme - tokens are passed via "Authorization: Bearer <token>"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

JWT_ALGORITHM = "HS256"


class Token(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(..., description="Seconds until expiration")


class TokenPayload(BaseModel):
    sub: int = Field(..., description="User ID subject")
    exp: int = Field(..., description="Expiration timestamp (epoch seconds)")
    iat: int = Field(..., description="Issued at timestamp (epoch seconds)")
    typ: str = Field("access", description="Token type: access or refresh")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)


class LoginResponse(Token):
    user: UserOut


class MeResponse(UserOut):
    pass


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def _verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except Exception:
        return False


def _encode_jwt(subject_user_id: int, expires_delta: Optional[timedelta] = None, typ: str = "access") -> str:
    if not settings.JWT_SECRET:
        # Fail loudly to surface misconfiguration
        raise RuntimeError("JWT_SECRET is not configured. Set JWT_SECRET in environment/.env")

    now = _now_utc()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_EXPIRES_MIN)
    expire = now + expires_delta

    payload = {
        "sub": subject_user_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "typ": typ,
    }
    encoded = jwt.encode(payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded


def _decode_jwt(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _create_access_token(user_id: int) -> Token:
    access_token = _encode_jwt(user_id, timedelta(minutes=settings.JWT_EXPIRES_MIN), typ="access")
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(timedelta(minutes=settings.JWT_EXPIRES_MIN).total_seconds()),
    )


def _create_refresh_token(user_id: int) -> Token:
    # Refresh token validity: 30 days by default (can be adjusted later)
    refresh_minutes = max(settings.JWT_EXPIRES_MIN * 24 * 30, settings.JWT_EXPIRES_MIN)
    refresh_token = _encode_jwt(user_id, timedelta(minutes=refresh_minutes), typ="refresh")
    return Token(
        access_token=refresh_token,
        token_type="bearer",
        expires_in=int(timedelta(minutes=refresh_minutes).total_seconds()),
    )


router = APIRouter(prefix="/auth", tags=["Auth"])


def _user_to_userout(user: User) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email and password.",
)
# PUBLIC_INTERFACE
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserOut:
    """Register a new user account.

    Args:
        payload (RegisterRequest): Email, password, and optional full_name.
        db (Session): Database session.

    Returns:
        UserOut: The created user without sensitive fields.

    Raises:
        HTTPException: 400 if email already exists.
    """
    existing = db.query(User).filter(User.email == str(payload.email).lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=str(payload.email).lower(),
        password_hash=_hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_userout(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and obtain JWT access token",
    description="Authenticate with email and password to get a JWT access token.",
)
# PUBLIC_INTERFACE
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> LoginResponse:
    """Login endpoint to obtain a JWT.

    Args:
        form_data (OAuth2PasswordRequestForm): Expects username (email) and password.
        db (Session): DB session.

    Returns:
        LoginResponse: Token info and user object.

    Raises:
        HTTPException: 400 for invalid credentials or inactive user.
    """
    email = form_data.username.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not _verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    token = _create_access_token(user.id)
    return LoginResponse(access_token=token.access_token, token_type=token.token_type, expires_in=token.expires_in, user=_user_to_userout(user))


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token")


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token.",
)
# PUBLIC_INTERFACE
def refresh_token(payload: RefreshRequest) -> Token:
    """Exchange refresh token for a new access token.

    Args:
        payload (RefreshRequest): Contains refresh_token.

    Returns:
        Token: New access token details.

    Raises:
        HTTPException: 401 if token invalid or not a refresh token.
    """
    payload_decoded = _decode_jwt(payload.refresh_token)
    if payload_decoded.typ != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return _create_access_token(payload_decoded.sub)


def _get_current_user_from_token(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Internal dependency to resolve current user from JWT bearer token."""
    payload = _decode_jwt(token)
    if payload.typ != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user = db.query(User).get(payload.sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user profile",
    description="Returns the profile of the currently authenticated user.",
)
# PUBLIC_INTERFACE
def me(current_user: User = Depends(_get_current_user_from_token)) -> MeResponse:
    """Return the authenticated user's profile."""
    return _user_to_userout(current_user)


# PUBLIC_INTERFACE
def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """FastAPI dependency to fetch the current authenticated user as a dict.

    This is provided for other modules to depend on without importing the router internals.

    Returns:
        Dict[str, Any]: Minimal user dict for downstream checks.
    """
    user = _get_current_user_from_token(token=token, db=db)
    return {"id": user.id, "email": user.email, "is_admin": user.role == UserRole.ADMIN}


# PUBLIC_INTERFACE
def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Admin guard dependency."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
