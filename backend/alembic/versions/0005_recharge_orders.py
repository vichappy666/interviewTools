"""create recharge_orders table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-29
"""
import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recharge_orders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("amount_usdt", sa.Numeric(20, 6), nullable=False),
        sa.Column("from_address", sa.String(64), nullable=False),
        sa.Column("to_address", sa.String(64), nullable=False),
        sa.Column("tx_hash", sa.String(80), nullable=True),
        sa.Column("tx_amount_usdt", sa.Numeric(20, 6), nullable=True),
        sa.Column("granted_seconds", sa.Integer, nullable=True),
        sa.Column("rate_per_usdt", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "submitted",
                "verifying",
                "succeeded",
                "failed",
                "expired",
                name="recharge_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("fail_reason", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("succeeded_at", sa.DateTime(timezone=False), nullable=True),
        sa.UniqueConstraint("tx_hash", name="uq_recharge_orders_tx_hash"),
    )
    op.create_index(
        "ix_recharge_orders_user_created",
        "recharge_orders",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_recharge_orders_status_expires",
        "recharge_orders",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recharge_orders_status_expires", table_name="recharge_orders"
    )
    op.drop_index(
        "ix_recharge_orders_user_created", table_name="recharge_orders"
    )
    op.drop_table("recharge_orders")
