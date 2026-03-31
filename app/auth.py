import os
import re
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db

load_dotenv()

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def validate_password(password: str) -> None:
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("at least one number")
    if re.search(r"^[a-zA-Z0-9]*$", password):
        errors.append("at least one special character")
    if errors:
        raise ValueError("Password must have: " + "; ".join(errors))


def get_password_hash(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + ":" + key.hex()


def verify_password(plain_password: str, stored_password: str) -> bool:
    try:
        salt_str, key_str = stored_password.split(":")
        salt = bytes.fromhex(salt_str)
        stored_key = bytes.fromhex(key_str)
        new_key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(new_key, stored_key)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_company(db: Session, email: str, password: str):
    company = db.query(models.Company).filter(models.Company.email == email).first()
    if not company or not company.hashed_password:
        return False
    if not verify_password(password, company.hashed_password):
        return False
    return company


def authenticate_blogger(db: Session, email: str, password: str):
    blogger = db.query(models.Blogger).filter(models.Blogger.email == email).first()
    if not blogger or not blogger.hashed_password:
        return False
    if not verify_password(password, blogger.hashed_password):
        return False
    return blogger


def authenticate_admin(db: Session, email: str, password: str):
    admin = db.query(models.Admin).filter(models.Admin.email == email).first()
    if not admin:
        return False
    if not verify_password(password, admin.hashed_password):
        return False
    return admin


def _decode_token(token: str) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        return payload
    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected JWT error: {e}")
        raise credentials_exception


async def get_current_company(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Company:
    payload = _decode_token(token)
    email = payload.get("sub")
    company = db.query(models.Company).filter(models.Company.email == email).first()
    if company is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Company not found")
    return company


async def get_current_blogger(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Blogger:
    payload = _decode_token(token)
    email = payload.get("sub")
    blogger = db.query(models.Blogger).filter(models.Blogger.email == email).first()
    if blogger is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Blogger not found")
    return blogger


async def get_current_admin(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Admin:
    payload = _decode_token(token)
    email = payload.get("sub")
    role = payload.get("role", "")
    if role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    admin = db.query(models.Admin).filter(models.Admin.email == email).first()
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin not found")
    return admin
