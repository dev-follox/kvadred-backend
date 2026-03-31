import logging
import os
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .constants import APP_NAME
from .database import engine, get_db
from .routers import affiliate_links, analytics, bloggers, companies, orders, products, admin, oauth
from .services.telegram_webhook import telegram_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title=APP_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

app.include_router(companies.router)
app.include_router(products.router)
app.include_router(affiliate_links.router)
app.include_router(bloggers.router)
app.include_router(orders.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(oauth.router)
app.include_router(telegram_service.router, prefix="/telegram", tags=["telegram"])


@app.on_event("startup")
async def startup_event():
    secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")
    if secret_key == "your-secret-key-here" or not secret_key:
        logger.warning("SECRET_KEY is not configured — authentication will not work properly")
    else:
        logger.info("SECRET_KEY is configured")

    domain = os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:8000"
    webhook_url = f"{domain}/telegram/webhook"

    if telegram_service.bot_token:
        await telegram_service.init_application()
        success = await telegram_service.set_webhook(webhook_url)
        if success:
            logger.info(f"Telegram webhook configured: {webhook_url}")
        else:
            logger.error("Failed to configure Telegram webhook")


@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    company = auth.authenticate_company(db, form_data.username, form_data.password)
    if company:
        access_token = auth.create_access_token(
            data={"sub": company.email, "role": "COMPANY", "company_id": company.id},
            expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "company_id": company.id,
            "blogger_id": None,
            "admin_id": None,
            "email": company.email,
            "name": company.company_name,
            "role": "COMPANY",
        }

    blogger = auth.authenticate_blogger(db, form_data.username, form_data.password)
    if blogger:
        access_token = auth.create_access_token(
            data={"sub": blogger.email, "role": "BLOGGER", "blogger_id": blogger.id},
            expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "company_id": None,
            "blogger_id": blogger.id,
            "admin_id": None,
            "email": blogger.email,
            "name": blogger.name,
            "role": "BLOGGER",
        }

    admin_user = auth.authenticate_admin(db, form_data.username, form_data.password)
    if admin_user:
        access_token = auth.create_access_token(
            data={"sub": admin_user.email, "role": "ADMIN", "admin_id": admin_user.id},
            expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "company_id": None,
            "blogger_id": None,
            "admin_id": admin_user.id,
            "email": admin_user.email,
            "name": admin_user.name,
            "role": "ADMIN",
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/")
async def root():
    return {"message": f"{APP_NAME} is running", "status": "healthy"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "telegram_bot_configured": telegram_service.bot_token is not None,
    }
