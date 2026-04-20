"""Designer rename, company subscription, analytics per affiliate link

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    bind = op.get_bind()
    return bind, sa.inspect(bind)


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_column(insp, table: str, col: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _pg_index_exists(bind, index_name: str) -> bool:
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'i' AND c.relname = :ix AND n.nspname = 'public'"
        ),
        {"ix": index_name},
    ).scalar()
    return r is not None


def _rename_bloggers_to_designers(bind, insp) -> None:
    has_b = _has_table(insp, "bloggers")
    has_d = _has_table(insp, "designers")
    if has_b and not has_d:
        op.execute("ALTER TABLE bloggers RENAME TO designers")
        return
    if has_b and has_d:
        n = bind.execute(sa.text("SELECT COUNT(*) FROM designers")).scalar()
        if n == 0:
            op.execute("DROP TABLE designers CASCADE")
            op.execute("ALTER TABLE bloggers RENAME TO designers")
            return
        raise RuntimeError(
            "Database has both 'bloggers' and 'designers' with data in 'designers'. "
            "Resolve manually (merge or drop the empty duplicate), then run migrate again."
        )
    # designers exists, bloggers gone — already renamed


def _rename_bloggers_indexes(bind, insp) -> None:
    if not _has_table(insp, "designers"):
        return
    pairs = [
        ("ix_bloggers_email", "ix_designers_email"),
        ("ix_bloggers_id", "ix_designers_id"),
        ("ix_bloggers_name", "ix_designers_name"),
    ]
    for old, new in pairs:
        if _pg_index_exists(bind, old) and not _pg_index_exists(bind, new):
            op.execute(sa.text(f'ALTER INDEX "{old}" RENAME TO "{new}"'))


def _rename_table_pair(bind, insp, old_name: str, new_name: str) -> None:
    """Rename old_name → new_name, or drop empty duplicate new_name from create_all."""
    has_old = _has_table(insp, old_name)
    has_new = _has_table(insp, new_name)
    if has_old and not has_new:
        op.execute(sa.text(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"'))
        return
    if has_old and has_new:
        n = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{new_name}"')).scalar()
        if n == 0:
            op.execute(sa.text(f'DROP TABLE "{new_name}" CASCADE'))
            op.execute(sa.text(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"'))
            return
        raise RuntimeError(
            f"Both '{old_name}' and '{new_name}' exist and '{new_name}' is not empty. "
            "Resolve manually, then run migrate again."
        )


def upgrade() -> None:
    bind, insp = _insp()

    if not _has_column(insp, "companies", "default_designer_bonus_percent"):
        op.add_column(
            "companies",
            sa.Column("default_designer_bonus_percent", sa.Float(), server_default="10", nullable=False),
        )
    if not _has_column(insp, "companies", "subscription_expires_at"):
        op.add_column(
            "companies",
            sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        "UPDATE companies SET subscription_expires_at = NOW() + INTERVAL '10 years' "
        "WHERE subscription_expires_at IS NULL"
    )

    bc_table = "blogger_companies" if _has_table(insp, "blogger_companies") else "designer_companies"
    if _has_table(insp, bc_table) and not _has_column(insp, bc_table, "bonus_percent_override"):
        op.add_column(
            bc_table,
            sa.Column("bonus_percent_override", sa.Float(), nullable=True),
        )

    if not _has_column(insp, "orders", "line_revenue"):
        op.add_column("orders", sa.Column("line_revenue", sa.Float(), nullable=True))
    if not _has_column(insp, "orders", "designer_bonus_amount"):
        op.add_column("orders", sa.Column("designer_bonus_amount", sa.Float(), nullable=True))
    if not _has_column(insp, "orders", "platform_fee_amount"):
        op.add_column("orders", sa.Column("platform_fee_amount", sa.Float(), nullable=True))
    if not _has_column(insp, "orders", "attachment_url"):
        op.add_column("orders", sa.Column("attachment_url", sa.String(), nullable=True))

    if _has_column(insp, "orders", "commission_amount"):
        op.execute(
            """
            UPDATE orders o
            SET line_revenue = ROUND(
                    (COALESCE(o.quantity, 0) * COALESCE(o.price_per_item, 0))::numeric, 2
                )::double precision,
                designer_bonus_amount = COALESCE(o.commission_amount, 0),
                platform_fee_amount = ROUND(
                    (COALESCE(o.quantity, 0) * COALESCE(o.price_per_item, 0) * 0.02)::numeric, 2
                )::double precision
            """
        )

    aff_col = "blogger_id" if _has_column(insp, "affiliate_links", "blogger_id") else "designer_id"
    if aff_col == "blogger_id":
        op.execute(
            """
            WITH keeper AS (
                SELECT DISTINCT ON (product_id, blogger_id) id AS keep_id, product_id, blogger_id
                FROM affiliate_links
                ORDER BY product_id, blogger_id, id
            )
            UPDATE orders o
            SET affiliate_link_id = k.keep_id
            FROM affiliate_links al
            JOIN keeper k ON al.product_id = k.product_id AND al.blogger_id = k.blogger_id
            WHERE o.affiliate_link_id = al.id AND al.id != k.keep_id
            """
        )
        op.execute(
            """
            WITH keeper AS (
                SELECT DISTINCT ON (product_id, blogger_id) id AS keep_id, product_id, blogger_id
                FROM affiliate_links
                ORDER BY product_id, blogger_id, id
            )
            DELETE FROM affiliate_links al
            USING keeper k
            WHERE al.product_id = k.product_id
              AND al.blogger_id = k.blogger_id
              AND al.id != k.keep_id
            """
        )

    cons = insp.get_unique_constraints("affiliate_links") if _has_table(insp, "affiliate_links") else []
    uq_names = {c["name"] for c in cons}
    if "uq_affiliate_designer_product" not in uq_names and aff_col == "blogger_id":
        op.create_unique_constraint(
            "uq_affiliate_designer_product",
            "affiliate_links",
            ["blogger_id", "product_id"],
        )

    if not _has_table(insp, "analytics_new"):
        op.execute(
            """
            CREATE TABLE analytics_new (
                id SERIAL NOT NULL PRIMARY KEY,
                affiliate_link_id INTEGER NOT NULL UNIQUE,
                product_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                designer_id INTEGER NOT NULL,
                visit_count INTEGER DEFAULT 0,
                order_count INTEGER DEFAULT 0,
                items_sold INTEGER DEFAULT 0,
                revenue DOUBLE PRECISION DEFAULT 0,
                designer_bonus_paid DOUBLE PRECISION DEFAULT 0,
                platform_fee_paid DOUBLE PRECISION DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE
            )
            """
        )

    bind, insp = _insp()
    analytics_already_new = _has_table(insp, "analytics") and _has_column(insp, "analytics", "affiliate_link_id")
    if analytics_already_new:
        if _has_table(insp, "analytics_new"):
            op.execute(sa.text("DROP TABLE IF EXISTS analytics_new CASCADE"))
    else:
        if _has_table(insp, "analytics_new") and _has_column(insp, "affiliate_links", aff_col):
            n_existing = bind.execute(sa.text("SELECT COUNT(*) FROM analytics_new")).scalar() or 0
            if n_existing == 0:
                if _has_column(insp, "analytics", "blogger_id"):
                    join_analytics = (
                        "LEFT JOIN analytics a ON a.product_id = al.product_id AND a.blogger_id = al.blogger_id"
                    )
                elif _has_table(insp, "analytics") and _has_column(insp, "analytics", "designer_id"):
                    join_analytics = (
                        "LEFT JOIN analytics a ON a.product_id = al.product_id AND a.designer_id = al.designer_id"
                    )
                else:
                    join_analytics = "LEFT JOIN analytics a ON 1=0"
                op.execute(
                    f"""
                    INSERT INTO analytics_new (
                        affiliate_link_id, product_id, company_id, designer_id,
                        visit_count, order_count, items_sold, revenue, designer_bonus_paid, platform_fee_paid
                    )
                    SELECT
                        al.id,
                        al.product_id,
                        p.company_id,
                        al.{aff_col},
                        COALESCE(a.visit_count, 0),
                        COALESCE(a.order_count, 0),
                        COALESCE(a.items_sold, 0),
                        COALESCE(a.revenue, 0),
                        COALESCE(a.commission_paid, 0),
                        ROUND((COALESCE(a.revenue, 0) * 0.02)::numeric, 2)::double precision
                    FROM affiliate_links al
                    JOIN products p ON p.id = al.product_id
                    {join_analytics}
                    ON CONFLICT (affiliate_link_id) DO NOTHING
                    """
                )
        if _has_table(insp, "analytics") and not _has_column(insp, "analytics", "affiliate_link_id"):
            op.drop_table("analytics")
        if _has_table(insp, "analytics_new"):
            op.execute(sa.text('ALTER TABLE analytics_new RENAME TO "analytics"'))
        bind, insp = _insp()
        if _has_table(insp, "analytics") and not _pg_index_exists(bind, "ix_analytics_id"):
            op.create_index(op.f("ix_analytics_id"), "analytics", ["id"], unique=False)

    bind, insp = _insp()
    _rename_bloggers_to_designers(bind, insp)
    bind, insp = _insp()
    _rename_bloggers_indexes(bind, insp)

    if _has_column(insp, "affiliate_links", "blogger_id"):
        op.execute("ALTER TABLE affiliate_links RENAME COLUMN blogger_id TO designer_id")

    bind, insp = _insp()
    cons = insp.get_unique_constraints("affiliate_links") if _has_table(insp, "affiliate_links") else []
    uq_names = {c["name"] for c in cons}
    if "uq_affiliate_designer_product" in uq_names:
        op.drop_constraint("uq_affiliate_designer_product", "affiliate_links", type_="unique")
    if "uq_affiliate_designer_product" not in {c["name"] for c in insp.get_unique_constraints("affiliate_links")}:
        op.create_unique_constraint(
            "uq_affiliate_designer_product", "affiliate_links", ["designer_id", "product_id"]
        )

    if _has_column(insp, "orders", "blogger_id"):
        op.execute("ALTER TABLE orders RENAME COLUMN blogger_id TO designer_id")

    bind, insp = _insp()
    _rename_table_pair(bind, insp, "blogger_invites", "designer_invites")
    bind, insp = _insp()
    if _has_table(insp, "designer_invites") and _has_column(insp, "designer_invites", "blogger_email"):
        op.execute("ALTER TABLE designer_invites RENAME COLUMN blogger_email TO designer_email")

    bind, insp = _insp()
    _rename_table_pair(bind, insp, "blogger_companies", "designer_companies")
    bind, insp = _insp()
    if _has_table(insp, "designer_companies") and _has_column(insp, "designer_companies", "blogger_id"):
        op.execute("ALTER TABLE designer_companies RENAME COLUMN blogger_id TO designer_id")

    if _has_column(insp, "products", "blogger_task_description"):
        op.execute("ALTER TABLE products RENAME COLUMN blogger_task_description TO designer_task_description")
    if _has_column(insp, "products", "commission_rate"):
        op.drop_column("products", "commission_rate")

    if _has_column(insp, "orders", "commission_amount"):
        op.drop_column("orders", "commission_amount")

    def _fk(name: str, ddl: str) -> None:
        r = bind.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        ).scalar()
        if r is None:
            op.execute(ddl)

    bind, insp = _insp()
    if not (_has_table(insp, "analytics") and _has_column(insp, "analytics", "affiliate_link_id")):
        return
    _fk(
        "analytics_affiliate_link_id_fkey",
        "ALTER TABLE analytics ADD CONSTRAINT analytics_affiliate_link_id_fkey "
        "FOREIGN KEY (affiliate_link_id) REFERENCES affiliate_links (id)",
    )
    _fk(
        "analytics_product_id_fkey",
        "ALTER TABLE analytics ADD CONSTRAINT analytics_product_id_fkey "
        "FOREIGN KEY (product_id) REFERENCES products (id)",
    )
    _fk(
        "analytics_company_id_fkey",
        "ALTER TABLE analytics ADD CONSTRAINT analytics_company_id_fkey "
        "FOREIGN KEY (company_id) REFERENCES companies (id)",
    )
    _fk(
        "analytics_designer_id_fkey",
        "ALTER TABLE analytics ADD CONSTRAINT analytics_designer_id_fkey "
        "FOREIGN KEY (designer_id) REFERENCES designers (id)",
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported for this refactor")
