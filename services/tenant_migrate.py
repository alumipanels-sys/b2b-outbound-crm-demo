"""Idempotent migration: add tenant_id / owner_user_id to business tables.

These columns are server-side ownership metadata (not exposed via schemas).
Existing single-tenant rows keep NULL = visible to all until assigned.
"""

import logging

logger = logging.getLogger(__name__)

TENANT_TABLES = {
    "prospects": ["tenant_id", "owner_user_id"],
    "intelligence": ["tenant_id", "owner_user_id"],
    "sequences": ["tenant_id", "owner_user_id"],
    "interactions": ["tenant_id", "owner_user_id"],
    "email_queue": ["tenant_id", "owner_user_id"],
    "knowledge_base": ["tenant_id"],
    "deals": ["tenant_id", "owner_user_id"],
    "sample_events": ["tenant_id", "owner_user_id"],
    "daily_email_stats": ["tenant_id"],
}


def apply_tenant_columns(conn):
    """Add missing ownership columns to existing tables. Safe to run repeatedly."""
    for table, cols in TENANT_TABLES.items():
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue  # table doesn't exist yet
        for col in cols:
            if col not in existing:
                logger.info("Adding tenant column %s to %s", col, table)
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER")
        conn.commit()

    # Query performance for "my customers" filters
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_prospects_owner ON prospects(owner_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_interactions_owner ON interactions(owner_user_id)")
        conn.commit()
    except Exception as e:
        logger.warning("Tenant index creation failed: %s", e)

    # ── tenants: license activation timestamps (idempotent) ──
    try:
        tcols = {r[1] for r in conn.execute("PRAGMA table_info(tenants)").fetchall()}
        if "activated_at" not in tcols:
            logger.info("Adding tenants.activated_at")
            conn.execute("ALTER TABLE tenants ADD COLUMN activated_at DATETIME")
        if "expires_at" not in tcols:
            logger.info("Adding tenants.expires_at")
            conn.execute("ALTER TABLE tenants ADD COLUMN expires_at DATETIME")
        conn.commit()
    except Exception as e:
        logger.warning("Tenant license columns migration failed: %s", e)
