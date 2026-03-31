import os
from typing import Dict, Any, Tuple, Union, Optional

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import models, auth

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


class OAuthService:
    @staticmethod
    def get_google_authorize_url(
        state: str, user_type: str = "blogger", redirect_uri: Optional[str] = None
    ) -> str:
        if not GOOGLE_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google OAuth not configured",
            )
        if redirect_uri is None:
            redirect_uri = f"{BASE_URL}/auth/google/callback"
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "response_type": "code",
            "state": f"{state}:{user_type}",
            "access_type": "offline",
            "prompt": "consent",
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"

    @staticmethod
    async def handle_google_callback(
        code: str,
        state: str,
        db: Session,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google OAuth not configured",
            )
        if redirect_uri is None:
            redirect_uri = f"{BASE_URL}/auth/google/callback"

        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to exchange code for token: {token_response.text}",
                )
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No access token received from Google",
                )

            user_info_response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_info_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to get user info: {user_info_response.text}",
                )
            user_info = user_info_response.json()

        user_type = "blogger"
        if ":" in state:
            _, user_type = state.split(":", 1)

        return {
            "email": user_info.get("email"),
            "name": user_info.get("name", user_info.get("given_name", "")),
            "provider_id": user_info.get("id"),
            "provider": "google",
            "user_type": user_type,
        }

    @staticmethod
    def get_or_create_user_from_oauth(
        oauth_data: Dict[str, Any],
        db: Session,
    ) -> Tuple[Union[models.Company, models.Blogger], bool]:
        email = oauth_data["email"]
        provider = oauth_data["provider"]
        provider_id = oauth_data["provider_id"]
        name = oauth_data["name"]
        user_type = oauth_data.get("user_type", "blogger")

        if user_type in ("company", "shop"):
            company = db.query(models.Company).filter(
                (models.Company.email == email)
                | (
                    (models.Company.oauth_provider == provider)
                    & (models.Company.oauth_provider_id == provider_id)
                )
            ).first()
            if company:
                if not company.oauth_provider:
                    company.oauth_provider = provider
                    company.oauth_provider_id = provider_id
                    db.commit()
                    db.refresh(company)
                return company, False

            new_company = models.Company(
                full_name=name,
                company_name=name,
                email=email,
                hashed_password=None,
                oauth_provider=provider,
                oauth_provider_id=provider_id,
            )
            db.add(new_company)
            db.commit()
            db.refresh(new_company)
            return new_company, True
        else:
            blogger = db.query(models.Blogger).filter(
                (models.Blogger.email == email)
                | (
                    (models.Blogger.oauth_provider == provider)
                    & (models.Blogger.oauth_provider_id == provider_id)
                )
            ).first()
            if blogger:
                if not blogger.oauth_provider:
                    blogger.oauth_provider = provider
                    blogger.oauth_provider_id = provider_id
                    db.commit()
                    db.refresh(blogger)
                return blogger, False

            new_blogger = models.Blogger(
                name=name,
                email=email,
                hashed_password=None,
                oauth_provider=provider,
                oauth_provider_id=provider_id,
            )
            db.add(new_blogger)
            db.commit()
            db.refresh(new_blogger)
            return new_blogger, True


oauth_service = OAuthService()
