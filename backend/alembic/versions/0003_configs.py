"""create configs kv table + seed defaults

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""
import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


_DEFAULTS = {
    "recharge.rate_per_usdt": 60,
    "recharge.min_amount_usdt": 5,
    "recharge.network": "shasta",
    "recharge.to_address": "",
    "session.max_concurrent": 5,
    "session.idle_timeout_seconds": 600,
    "asr.volcengine": {},
    "llm.providers": [],
    "llm.default": "deepseek",
}


def upgrade() -> None:
    op.create_table(
        "configs",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # SQLAlchemy JSON column auto-encodes Python values, so we pass raw values
    # for compatibility across SQLite (tests) and MySQL (production).
    table = sa.table(
        "configs",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
    )
    rows = [{"key": k, "value": v} for k, v in _DEFAULTS.items()]
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_table("configs")
