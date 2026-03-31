# Kvadred Backend

Affiliate sales platform backend — companies list products, invite bloggers, track affiliate link clicks, orders, commissions, and analytics.

## Tech Stack

- **FastAPI** + **SQLAlchemy** + **PostgreSQL**
- **Alembic** for migrations
- **JWT** + **Google OAuth** authentication
- **Telegram bot** for order notifications

## Modules

| Module | Description |
|---|---|
| Companies | Register, manage profile, link Telegram |
| Products | CRUD with commission rates per product |
| Bloggers | Self-register or accept company invite, multi-company |
| Affiliate Links | Auto-generated unique codes, click tracking |
| Orders | Auto (via link) + manual entry, commission calculation |
| Analytics | Full dashboard: visits, conversions, revenue, blogger rankings |
| Admin | Full platform management |

## Quick Start

```bash
cp .env.example .env
# edit .env with your DATABASE_URL and SECRET_KEY

pip install -r requirements.txt

alembic upgrade head

uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`

## Auth Roles

| Role | Token claim |
|---|---|
| Company | `role: COMPANY` |
| Blogger | `role: BLOGGER` |
| Admin | `role: ADMIN` |

All protected routes require `Authorization: Bearer <token>`.

## Environment Variables

See `.env.example` for all required and optional variables.
