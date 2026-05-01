import datetime
import hashlib
import secrets
import base64
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, delete as sa_delete
from jose import JWTError, jwt

from config import JWT_SECRET, JWT_ALG, JWT_EXPIRE, logger
from database import get_db
from models import User, PasswordResetToken
from services.email_service import notify_new_user, _send_reset_email

router = APIRouter()

_PBKDF2_ITERS = 260_000


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"{salt}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, hashed: str) -> bool:
    try:
        salt, stored = hashed.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ITERS)
        return base64.b64encode(dk).decode() == stored
    except Exception:
        logger.warning("Password verification error", exc_info=True)
        return False


def create_token(user_id: int, email: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRE)
    return jwt.encode({"sub": str(user_id), "email": email, "exp": expire}, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    token: str
    email: str
    user_id: int

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/auth/register", response_model=AuthResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, hashed_pw=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    notify_new_user(user.email)
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)


@router.post("/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)


@router.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id, "email": current_user.email}


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user  = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        db.execute(sa_delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        token   = secrets.token_urlsafe(32)
        expires = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires))
        db.commit()
        threading.Thread(target=_send_reset_email, args=(user.email, token), daemon=True).start()
    return {"ok": True}  # always ok — prevents email enumeration


@router.post("/auth/reset-password", response_model=AuthResponse)
def reset_password_endpoint(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    rt = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == body.token,
            PasswordResetToken.used == 0,
        )
    ).scalar_one_or_none()
    if not rt or rt.expires_at < datetime.datetime.utcnow():
        raise HTTPException(400, "Reset link is invalid or has expired")
    user = db.execute(select(User).where(User.id == rt.user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(400, "User not found")
    user.hashed_pw = hash_password(body.new_password)
    rt.used = 1
    db.commit()
    return AuthResponse(token=create_token(user.id, user.email), email=user.email, user_id=user.id)
