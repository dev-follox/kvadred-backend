import base64
import json
import logging
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, schemas
from ..database import get_db
from ..services.oauth import oauth_service

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

router = APIRouter(prefix="/auth", tags=["oauth"])

# In-memory state store (replace with Redis in production for multi-worker setups)
state_store: dict = {}


class GoogleExchangeRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str
    user_type: str = "blogger"


@router.get("/google/login")
async def google_login(user_type: str = "blogger"):
    state = secrets.token_urlsafe(32)
    state_store[state] = True
    try:
        url = oauth_service.get_google_authorize_url(state, user_type)
        return RedirectResponse(url=url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate Google login: {e}")


@router.get("/google/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    state_token = state.split(":")[0] if ":" in state else state
    if state_token not in state_store:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    del state_store[state_token]

    try:
        oauth_data = await oauth_service.handle_google_callback(code, state, db)
        user, is_new = oauth_service.get_or_create_user_from_oauth(oauth_data, db)
        user_type = oauth_data.get("user_type", "blogger")
        token_data = _build_token_data(user, user_type, is_new)

        frontend_url = FRONTEND_URL.rstrip("/")
        token_encoded = base64.urlsafe_b64encode(json.dumps(token_data).encode()).decode()
        return RedirectResponse(
            url=f"{frontend_url}/#/auth/callback?token={token_encoded}", status_code=302
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {e}\n{traceback.format_exc()}")


@router.get("/google/authorize-url")
async def get_google_authorize_url(user_type: str = "blogger"):
    state = secrets.token_urlsafe(32)
    state_store[state] = True
    frontend_redirect_uri = f"{FRONTEND_URL.rstrip('/')}/auth/callback"
    auth_url = oauth_service.get_google_authorize_url(
        state=state, user_type=user_type, redirect_uri=frontend_redirect_uri
    )
    return JSONResponse(
        content={
            "authorization_url": auth_url,
            "state": state,
            "redirect_uri": frontend_redirect_uri,
            "frontend_callback_path": "/#/auth/callback",
        }
    )


@router.post("/google/exchange")
async def exchange_google_code(request: GoogleExchangeRequest, db: Session = Depends(get_db)):
    state_token = request.state.split(":")[0] if ":" in request.state else request.state
    if state_token not in state_store:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    del state_store[state_token]

    try:
        oauth_data = await oauth_service.handle_google_callback(
            code=request.code,
            state=request.state,
            db=db,
            redirect_uri=request.redirect_uri,
        )
        oauth_data["user_type"] = request.user_type or oauth_data.get("user_type", "blogger")
        user, is_new = oauth_service.get_or_create_user_from_oauth(oauth_data, db)
        user_type = request.user_type or oauth_data.get("user_type", "blogger")
        token_data = _build_token_data(user, user_type, is_new)
        return JSONResponse(content=token_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to exchange code: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to exchange code: {e}")


def _build_token_data(user, user_type: str, is_new: bool) -> dict:
    from .. import models

    if user_type in ("company", "shop"):
        access_token = auth.create_access_token(
            data={"sub": user.email, "role": "COMPANY", "company_id": user.id},
            expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "company_id": user.id,
            "blogger_id": None,
            "admin_id": None,
            "email": user.email,
            "name": getattr(user, "company_name", None) or getattr(user, "name", ""),
            "role": "COMPANY",
            "is_new_user": is_new,
        }
    else:
        access_token = auth.create_access_token(
            data={"sub": user.email, "role": "BLOGGER", "blogger_id": user.id},
            expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "company_id": None,
            "blogger_id": user.id,
            "admin_id": None,
            "email": user.email,
            "name": user.name,
            "role": "BLOGGER",
            "is_new_user": is_new,
        }
