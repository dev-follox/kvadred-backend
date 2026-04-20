# Kvadred API — Full endpoint reference

**Frontend migration:** see `FRONTEND_REFACTOR_PROMPT.md` in this repo (copy into `../deltahub-frontend` when integrating).

Base URL is your deployment origin (for example `http://localhost:8000`). All authenticated routes expect:

```http
Authorization: Bearer <access_token>
```

Unless noted, request bodies are JSON with `Content-Type: application/json`.

---

## Authentication and roles

### Login (`POST /token`)

OAuth2 password flow (form body, not JSON):


| Field      | Description      |
| ---------- | ---------------- |
| `username` | Account email    |
| `password` | Account password |


**Response** (`Token`):


| Field          | Type       | Description                       |
| -------------- | ---------- | --------------------------------- |
| `access_token` | string     | JWT                               |
| `token_type`   | string     | Always `bearer`                   |
| `company_id`   | int | null | Set when `role` is `COMPANY`      |
| `designer_id`  | int | null | Set when `role` is `DESIGNER`     |
| `admin_id`     | int | null | Set when `role` is `ADMIN`        |
| `email`        | string     |                                   |
| `name`         | string     |                                   |
| `role`         | string     | `COMPANY`, `DESIGNER`, or `ADMIN` |


**JWT payload** (for debugging / custom clients): `sub` (email), `role`, and `company_id` or `designer_id` or `admin_id` as applicable.

### Roles summary


| Role         | Typical usage                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------ |
| **COMPANY**  | Manage catalog, subscription, designer invites, designer bonus overrides, orders, read analytics |
| **DESIGNER** | Browse subscribed companies, catalogs, create affiliate links, manual orders, own stats          |
| **ADMIN**    | Migrations, list/patch/delete companies and designers, subscription dates                        |
| **Public**   | Registration, affiliate link resolution, visit tracking, checkout order creation                 |


---

## Company subscription rules

- `**subscription_expires_at`**: UTC datetime. If `null` or in the past, the company is treated as **inactive**.
- **Inactive company**: hidden from designer company catalog; affiliate resolution and new orders blocked; **read-only analytics** still allowed for the company token (dashboard, filtered analytics, order listing where not blocked by implementation).
- **Writes** (products, profile, passwords, Telegram link, designer invites, designer bonus edits, affiliate link deletion, order status updates, order field updates) require an **active** subscription (`subscription_expires_at` in the future).

Default **designer bonus** for a company is `default_designer_bonus_percent` (0–100). Per-designer override lives on `DesignerCompany.bonus_percent_override`.

---

## Money model (orders)

For each sale (line revenue = `price_per_item × quantity` at order time):

- **Designer bonus** = effective bonus % × line revenue (effective % = override on `DesignerCompany` if set, else company default).
- **Platform fee** = 2% of line revenue (company-facing; not deducted from designer bonus).

Stored on each order: `line_revenue`, `designer_bonus_amount`, `platform_fee_amount`.

**Rollup** (`analytics` table): one row per **affiliate link**; updated on link visits and when an order moves to `processed`.

---

## Public routes

### `GET /`

Health-style message.

### `GET /health`

JSON: `status`, `telegram_bot_configured`.

### `POST /companies/`

Register a company (no auth).

**Body** (`CompanyCreate`): `full_name`, `email`, `phone_number?`, `company_name`, `description?`, `password` (strength rules apply), `**default_designer_bonus_percent`** (0–100).

**Note:** `subscription_expires_at` is not set by self-signup (inactive until an admin sets it via `PATCH /admin/companies/{id}`).

### `POST /designers/`

Register a designer (no auth).

**Body** (`DesignerCreate`): `name`, `email`, `bio?`, `password`.

### `GET /designers/invites/{token}`

Public invite metadata (`DesignerInvite`). Fails if expired or not `pending`.

### `POST /designers/invites/{token}/accept`

Accept invite; creates designer if needed; returns `**Token`** (same shape as `/token`).

**Body** (`DesignerInviteAccept`): `token` (redundant with path; may still be sent), `name`, `password`.

### Designer invite flow (company → designer)

1. **Company creates an invite** — `POST /companies/me/designer-invites` (authenticated company, **active subscription**). Body: `{ "designer_email": "<email>" }`.
2. **Stored row** — `DesignerInvite`: `company_id`, `designer_email`, random `token`, `status=pending`, `expires_at` = **72 hours** after creation (`INVITE_EXPIRE_HOURS` in the companies router).
3. **No outbound email** — The API does **not** send email or other notifications for invites. The response includes the `token`; the **frontend or product** must deliver a link (e.g. `https://<app>/designers/invites/<token>` or a deep link that calls the API) to the designer by email, SMS, etc.
4. **Designer previews (optional)** — `GET /designers/invites/{token}` returns invite details if still `pending` and not expired (expired invites may be marked `expired` on read).
5. **Designer accepts** — `POST /designers/invites/{token}/accept` with `name` and `password` (password strength rules apply).
6. **Account handling** — If no `Designer` exists with `invite.designer_email`, one is **created** with that email, `name`, and hashed `password`. If a designer **already exists** with that email, they are **linked only**; the accept body’s `password` is **not** used to change their existing password.
7. **Company link** — If no `DesignerCompany` row exists for `(designer_id, company_id)`, one is created (**no** `bonus_percent_override` → effective bonus is the company’s `default_designer_bonus_percent` until the company sets an override via `PATCH /companies/me/designers/{id}/bonus`).
8. **Invite status** — Set to `accepted`. Response is a **JWT login** (`Token`) with `role: DESIGNER` so the designer can be signed in immediately.
9. **Afterwards** — The designer appears under `GET /companies/me/designers` and can use designer endpoints (catalog, affiliate links, etc.) for that company per normal rules.

### `POST /orders/`

Create an order (checkout; **no auth**). Company must have active subscription.

**Body** (`OrderCreate`): `product_id`, `designer_id`, `quantity`, `price_per_item`, `client_phone`, `client_name?`, `note?`, `affiliate_link_id?`, `is_manual`.

If `affiliate_link_id` is omitted, the server **creates or reuses** the single affiliate link for `(designer_id, product_id)` and links the order.

### `GET /affiliate-links/{code}`

Resolve affiliate link by public `code`; increments click count and rollup visit count. **403** if the product’s company subscription is inactive.

### `POST /analytics/visit`

Increment visit count for a link (alternative to GET on affiliate link).

**Body** (`AffiliateVisitRequest`): `{ "code": "<affiliate code>" }`.

### `GET /products/{product_id}`

Product detail (no auth).

### `GET /products/images/{filename}`

Serve uploaded product image file.

---

## Google OAuth (`/auth`)


| Method | Path                         | Description                                                                                                                       |
| ------ | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/auth/google/login`         | Query `user_type`: `designer` (default) or `company`. Legacy `blogger` is accepted and mapped to `designer`. Redirects to Google. |
| GET    | `/auth/google/callback`      | OAuth callback; redirects to frontend with token in query (base64 JSON).                                                          |
| GET    | `/auth/google/authorize-url` | JSON with `authorization_url`, `state`, `redirect_uri`, `frontend_callback_path`.                                                 |
| POST   | `/auth/google/exchange`      | **Body:** `code`, `state`, `redirect_uri`, `user_type?`. Returns token JSON (same fields as `/token` plus `is_new_user`).         |


---

## Telegram (`/telegram`)


| Method | Path                | Description                                      |
| ------ | ------------------- | ------------------------------------------------ |
| POST   | `/telegram/webhook` | Telegram bot webhook (used by Telegram servers). |


---

## COMPANY role (`Authorization: Bearer` company token)

Prefix `**/companies`** (except `POST /companies/` which is public).


| Method | Path                                          | Auth    | Description                                                                                                              |
| ------ | --------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/companies/me`                               | Company | Current company profile (includes `default_designer_bonus_percent`, `subscription_expires_at`).                          |
| PUT    | `/companies/me`                               | Company | **Body:** `CompanyUpdate`. **Requires active subscription.**                                                             |
| PUT    | `/companies/me/password`                      | Company | **Body:** `PasswordUpdate`. **Requires active subscription.**                                                            |
| DELETE | `/companies/me`                               | Company | Delete company and related data. **Requires active subscription.**                                                       |
| GET    | `/companies/{company_id}`                     | Company | Same as `me` only if `company_id` matches token.                                                                         |
| POST   | `/companies/{company_id}/telegram`            | Company | **Body:** `TelegramLink`. **Requires active subscription.**                                                              |
| GET    | `/companies/{company_id}/telegram/setup`      | Company | Instructions + link status.                                                                                              |
| POST   | `/companies/me/designer-invites`              | Company | **Body:** `{ "designer_email": "..." }`. **Requires active subscription.**                                               |
| GET    | `/companies/me/designers`                     | Company | Linked designers with `effective_bonus_percent`. **Requires active subscription.**                                       |
| PATCH  | `/companies/me/designers/{designer_id}/bonus` | Company | **Body:** `DesignerBonusUpdate` — `bonus_percent_override` (0–100) or `null` to clear. **Requires active subscription.** |
| DELETE | `/companies/me/affiliate-links/{link_id}`     | Company | Remove a designer’s link for this company’s product (moderation). **Requires active subscription.**                      |


Prefix `**/products`**:


| Method | Path                               | Description                                                                                  |
| ------ | ---------------------------------- | -------------------------------------------------------------------------------------------- |
| GET    | `/products/`                       | List own products. **Requires active subscription.**                                         |
| POST   | `/products/`                       | **Body:** `ProductCreate` (`company_id` must match token). **Requires active subscription.** |
| PUT    | `/products/{product_id}`           | **Body:** `ProductUpdate`. **Requires active subscription.**                                 |
| DELETE | `/products/{product_id}`           | **Requires active subscription.**                                                            |
| GET    | `/products/{product_id}/orders`    | Orders for product.                                                                          |
| GET    | `/products/{product_id}/analytics` | Rollup rows (`Analytics`) for that product.                                                  |
| POST   | `/products/upload-image`           | Multipart `image` file. **Requires active subscription.**                                    |


Prefix `**/affiliate-links`**: company does **not** create links; designers do. Company may **DELETE** `/companies/me/affiliate-links/{link_id}` only.

Prefix `**/orders`**:


| Method | Path                        | Description                                                                                                                                                                                      |
| ------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/orders/`                  | All orders for company’s products.                                                                                                                                                               |
| GET    | `/orders/{order_id}`        | Order with product relation.                                                                                                                                                                     |
| PUT    | `/orders/{order_id}/status` | Query/body: new `OrderStatus` — `waiting_to_process`, `processed`, `cancelled`. When set to `**processed**`, rollup is updated for the order’s affiliate link. **Requires active subscription.** |
| PUT    | `/orders/{order_id}`        | **Body:** `OrderUpdate`. **Requires active subscription.**                                                                                                                                       |


Prefix `**/analytics`**:


| Method | Path                                                  | Description                                                                                                                                    |
| ------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/analytics/dashboard`                                | Full dashboard (`AnalyticsDashboard`: totals, `designer_rankings`, `per_link`). Allowed even if subscription inactive (read-only analytics).   |
| GET    | `/analytics/leaderboard`                              | Same as dashboard’s `designer_rankings`.                                                                                                       |
| GET    | `/analytics/designer/{designer_id}`                   | Per-link rollup rows for that designer scoped to this company’s products.                                                                      |
| GET    | `/analytics/company/products`                         | Query: `sort` = `revenue` | `designer_bonus` | `platform_fee`, `from` / `to` (ISO datetimes, UTC). Aggregates **processed** orders by product. |
| GET    | `/analytics/company/products/{product_id}/designers`  | Same query params; breakdown by designer for one product.                                                                                      |
| GET    | `/analytics/company/designers`                        | Same query params; aggregate by designer.                                                                                                      |
| GET    | `/analytics/company/designers/{designer_id}/products` | Same query params; products sold by one designer for this company.                                                                             |


---

## DESIGNER role

Prefix `**/designers`**:


| Method | Path                                                 | Description                                                                                                                                                        |
| ------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/designers/me`                                      | Current designer.                                                                                                                                                  |
| PUT    | `/designers/me`                                      | **Body:** `DesignerUpdate`.                                                                                                                                        |
| PUT    | `/designers/me/password`                             | **Body:** `PasswordUpdate`.                                                                                                                                        |
| POST   | `/designers/me/telegram`                             | **Body:** `TelegramLink`.                                                                                                                                          |
| GET    | `/designers/catalog/companies`                       | Companies with **active** subscription only (marketplace list).                                                                                                    |
| GET    | `/designers/catalog/companies/{company_id}/products` | Catalog for that company (403 if company inactive).                                                                                                                |
| GET    | `/designers/me/companies`                            | Companies linked via `DesignerCompany` (invites, self-join, or auto-created on first order).                                                                       |
| POST   | `/designers/me/join-company/{company_id}`            | Self-serve link to company (403 if company inactive).                                                                                                              |
| POST   | `/designers/me/manual-orders`                        | **Body:** `DesignerManualOrderCreate` — creates/reuses affiliate link, `is_manual` order in `waiting_to_process`. Optional `attachment_url` (external URL string). |


Prefix `**/affiliate-links`**:


| Method | Path                         | Description                                                                                                                      |
| ------ | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/affiliate-links/`          | **Body:** `{ "product_id": N }`. Creates or returns existing link (max one per designer+product). Ensures `DesignerCompany` row. |
| GET    | `/affiliate-links/my-links`  | Links with nested product/designer and rollup fields + `effective_bonus_percent`.                                                |
| DELETE | `/affiliate-links/{link_id}` | Delete own link (`link_id` is numeric id, not code).                                                                             |


Prefix `**/orders`**:


| Method | Path                | Description                                       |
| ------ | ------------------- | ------------------------------------------------- |
| GET    | `/orders/my-orders` | Orders for current designer (`OrderWithDetails`). |


Prefix `**/analytics**`:


| Method | Path                  | Description                                                          |
| ------ | --------------------- | -------------------------------------------------------------------- |
| GET    | `/analytics/my-stats` | All `Analytics` rollup rows where `designer_id` is the current user. |


**Products** (designer):


| Method | Path                        | Description                                                             |
| ------ | --------------------------- | ----------------------------------------------------------------------- |
| GET    | `/products/for-me`          | Products the designer has at least one affiliate link for.              |
| GET    | `/products/for-me/detailed` | Same plus `affiliate_code`, `click_count`, `designer_task_description`. |


---

## ADMIN role

Prefix `**/admin`**. All routes require admin JWT.


| Method | Path                             | Description                                                                                                         |
| ------ | -------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| POST   | `/admin/migrate`                 | Run Alembic to head; may create default admin if empty DB.                                                          |
| POST   | `/admin/create`                  | **Body:** `AdminCreate` — create another admin.                                                                     |
| GET    | `/admin/companies`               | Paginate: `skip`, `limit`.                                                                                          |
| GET    | `/admin/companies/{company_id}`  | Company detail.                                                                                                     |
| PATCH  | `/admin/companies/{company_id}`  | **Body:** `CompanySubscriptionAdminUpdate` — set `subscription_expires_at` and/or `default_designer_bonus_percent`. |
| DELETE | `/admin/companies/{company_id}`  | Hard delete company cascade.                                                                                        |
| GET    | `/admin/designers`               | List designers.                                                                                                     |
| GET    | `/admin/designers/{designer_id}` | Designer detail.                                                                                                    |
| DELETE | `/admin/designers/{designer_id}` | Hard delete designer cascade.                                                                                       |
| GET    | `/admin/orders`                  | All orders.                                                                                                         |
| GET    | `/admin/products`                | All products.                                                                                                       |
| GET    | `/admin/analytics`               | All rollup rows.                                                                                                    |


---

## Enums and validation

### `OrderStatus`

- `waiting_to_process`
- `processed`
- `cancelled`

### `InviteStatus`

- `pending`
- `accepted`
- `expired`

### Password rules (company, designer, admin create, password change)

Minimum 8 characters, upper and lower case, digit, special character, not alphanumeric-only.

---

## CORS and methods

`PATCH` is enabled for company bonus and admin company patch.

---

## Typical frontend flows

1. **Company onboarding:** `POST /companies` → admin sets `PATCH /admin/companies/{id}` with `subscription_expires_at` → company logs in `POST /token` → `POST /products`, etc.
2. **Designer onboarding:** `POST /designers` or invite flow `GET /designers/invites/{token}` → `POST /designers/invites/.../accept` → `GET /designers/catalog/companies` → `GET .../products` → `POST /affiliate-links/`.
3. **Checkout:** Storefront calls `POST /orders` with `designer_id`, `product_id`, optional `affiliate_link_id`; company later `PUT /orders/{id}/status` to `processed`.
4. **Manual sale:** Designer `POST /designers/me/manual-orders`; company processes order as usual.

For a machine-readable contract, open `**/docs`** (Swagger UI) or `**/redoc**` when the server is running.