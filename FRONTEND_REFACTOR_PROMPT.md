## Goal

Refactor the frontend to match the **designer-centric** affiliate model, renamed APIs, new auth claims, subscription gating, and new analytics/order fields. Remove all **blogger** naming and legacy flows where **companies** created affiliate links.

---

## 1. Naming and routes (breaking)


| Old                                                      | New                                                                                                   |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `/bloggers`, `Blogger`, `blogger_id`                     | `/designers`, `Designer`, `designer_id`                                                               |
| JWT / token `role: BLOGGER`                              | `role: DESIGNER`                                                                                      |
| Token payload / login response `blogger_id`              | `designer_id`                                                                                         |
| `commission_rate` on products                            | **Removed** — bonus is company default + per-designer override                                        |
| `blogger_task_description` on products                   | `designer_task_description`                                                                           |
| Company creates affiliate link with `blogger_id` in body | **Removed** — only `**POST /affiliate-links/`** as authenticated **designer** with `{ "product_id" }` |
| `GET /bloggers/...` invite paths                         | `GET /designers/invites/{token}`, `POST /designers/invites/{token}/accept`                            |
| Company listing “bloggers”                               | `GET /companies/me/designers`                                                                         |
| Company invite blogger                                   | `POST /companies/me/designer-invites` body `{ "designer_email" }`                                     |
| OAuth default `user_type=blogger`                        | Use `**designer`** (backend still accepts `blogger` as alias → treat as `designer` in UI)             |


Update **all** API clients, types, stores, route guards, and persisted tokens/localStorage keys.

---

## 2. Authentication

- `**POST /token`**: response shape uses `designer_id` instead of `blogger_id`; `role` is `DESIGNER` for designers.
- **Google OAuth** (`/auth/google/*`): token JSON same as password login; default `user_type` should be `**designer`** for designer login flows.
- **JWT decoding** (if any): read `designer_id` and `DESIGNER` role.
- **Route protection**: map `DESIGNER` to former blogger-only pages.

---

## 3. Company signup and settings

- **Registration** (`POST /companies`): require `**default_designer_bonus_percent`** (0–100) in the form.
- New companies may have `**subscription_expires_at: null**` until an admin sets it → company is **inactive** for catalog and writes. UX: show “pending activation” or contact admin; do not assume full access after signup.
- **Company profile** (`Company`): display and optionally edit `default_designer_bonus_percent`, `subscription_expires_at` (read-only for company if only admin sets it — today only admin `PATCH /admin/companies/{id}` sets subscription).

---

## 4. Designer flows (new / changed)

1. **Marketplace:** `GET /designers/catalog/companies` — only companies with **active** subscription. Use for “browse companies”.
2. **Catalog:** `GET /designers/catalog/companies/{companyId}/products`.
3. **Partnerships:** `GET /designers/me/companies`; `**POST /designers/me/join-company/{companyId}`** for self-serve.
4. **Affiliate links:** `POST /affiliate-links/` with `{ product_id }`; `**GET /affiliate-links/my-links`** for dashboard (includes rollup: visits, orders, revenue, `designer_bonus_paid`, `platform_fee_paid`, `effective_bonus_percent`).
5. **Public link / landing:** `GET /affiliate-links/{code}` (still by **code** string in path — ensure router order does not treat `my-links` as a code).
6. **Visits:** Prefer `**POST /analytics/visit`** with `{ "code" }` or keep using GET resolve endpoint — both increment visits.
7. **Manual orders:** `POST /designers/me/manual-orders` with `DesignerManualOrderCreate` (optional `attachment_url` string).
8. **Designer orders list:** `GET /orders/my-orders` (was blogger path).

Remove UI for **company** creating links or picking a blogger id.

---

## 5. Company flows (new / changed)

- **Designer management:** `GET /companies/me/designers`, `**PATCH /companies/me/designers/{designerId}/bonus`** with `{ "bonus_percent_override": number | null }`.
- **Invites:** `POST /companies/me/designer-invites` with `{ "designer_email" }` (no longer under `/bloggers/invite`).
- **Moderation:** `DELETE /companies/me/affiliate-links/{linkId}` (numeric link id).
- **Subscription gating:** If API returns **403** with subscription message, disable writes (products CRUD, profile, password, telegram, invites, bonus patch, order status, product upload) but **keep analytics dashboards** readable where backend allows.

### Designer invite UX (company → designer)

Implement this flow explicitly in the frontend; the backend **does not send email**.

1. **Company** calls `POST /companies/me/designer-invites` with `{ "designer_email" }` (requires active subscription). Response is a `DesignerInvite` including `token`, `expires_at` (~**72 hours**), `company_id`, `designer_email`, `status`.
2. **Deliver the link** — Build a URL or in-app route the designer can open (e.g. `/designers/invites/:token` or `/accept-invite?token=...`). Optionally copy a **magic link** for pasting into email clients, or integrate your own email provider (not part of this API).
3. **Preview** — `GET /designers/invites/{token}` (public) to show company context before sign-up; handle `404` / expired / not `pending`.
4. **Accept** — `POST /designers/invites/{token}/accept` with `name`, `password` (and `token` if your client sends it in the body). Response is a full **`Token`** (`DESIGNER`); store it like a normal login.
5. **New vs existing designer** — New account: `name` + `password` create the user. **Existing** email: only **links** to the company; **do not assume** the password field updates their account (it does not on the server).
6. **Post-accept** — Designer should land in the app as logged-in; they appear on the company’s `GET /companies/me/designers` list with default bonus until the company sets `bonus_percent_override`.

---

## 6. Orders and checkout

- `**POST /orders`** body: `designer_id` (not `blogger_id`). Optional `affiliate_link_id`; if omitted, backend creates/reuses link.
- Order model: show `**line_revenue**`, `**designer_bonus_amount**`, `**platform_fee_amount**`; remove display of old `commission_amount` / product `commission_rate`.
- **Statuses:** unchanged enum strings (`waiting_to_process`, `processed`, `cancelled`).

---

## 7. Analytics UI

- **Company dashboard:** `GET /analytics/dashboard` — totals include `total_designer_bonus`, `total_platform_fee`; rankings use `**designer_rankings`** (not `blogger_rankings`); per-link list is `**per_link**`.
- **Filtered reports (UTC, processed orders only):**
  - `GET /analytics/company/products?from=&to=&sort=revenue|designer_bonus|platform_fee`
  - `GET /analytics/company/products/{productId}/designers?...`
  - `GET /analytics/company/designers?...`
  - `GET /analytics/company/designers/{designerId}/products?...`
- **Designer:** `GET /analytics/my-stats` — rollup rows keyed by **affiliate link** (each row has `affiliate_link_id`, `product_id`, `company_id`, `designer_id`).

Build charts/tables for revenue vs designer bonus vs platform fee as separate columns.

---

## 8. Products UI

- Remove **commission rate** fields from forms and tables.
- Rename labels/help text from “blogger” to **designer**; use `**designer_task_description`** in API payloads.
- `**GET /products/**` for company requires active subscription — handle 403.
- `**GET /products/{id}**` is still public for product page (no visit side-effect from old `blogger_id` query — remove that query param if present).

---

## 9. Admin / internal tools (if present in frontend)

- Endpoints: `/admin/designers`, `/admin/designers/{id}`, `**PATCH /admin/companies/{id}**` for `subscription_expires_at` and `default_designer_bonus_percent`.
- Remove `/admin/bloggers` usage.

---

## 10. Types and code search checklist

Search and replace (case-sensitive where needed):

- `blogger`, `Blogger`, `BLOGGER`, `blogger_id`, `/bloggers`
- `commission_rate`, `commission_amount`, `blogger_task_description`
- `BloggerRanking`, `blogger_rankings`, `per_product` dashboard field if you typed old shape → use `**DesignerRanking**`, `**designer_rankings**`, `**per_link**`

Regenerate or hand-update **OpenAPI-generated** clients if used.

---

## 11. Acceptance criteria

- Designer can register, log in, list subscribed companies, open catalog, create link, see `my-links` with rollup + effective bonus %.
- Company can sign up with default bonus %; after admin sets subscription date, company can manage products and see analytics.
- Company can invite designers, list linked designers, patch per-designer bonus override.
- Checkout creates orders with `designer_id`; optional `affiliate_link_id`.
- No remaining references to blogger routes or `blogger_id` in token handling.
- Analytics screens show revenue, designer bonus, and platform fee consistently.
- OAuth and password login both store/use `designer_id` + `DESIGNER` role.

---

## 12. Suggested implementation order

1. Shared API types + auth slice (token, role, ids).
2. Designer pages (catalog, links, manual orders, my-stats).
3. Company pages (designers list, invites, bonus patch, subscription messaging).
4. Products (remove commission, rename task field).
5. Orders and checkout payload migration.
6. Analytics dashboards and new query-param reports.
7. Admin screens if applicable.
8. End-to-end test against running `kvadred-backend` with migrated DB (`POST /admin/migrate` or Alembic).
