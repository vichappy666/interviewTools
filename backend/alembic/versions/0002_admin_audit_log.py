"""create admin_audit_log

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29
"""
import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("admin_id", sa.BigInteger, nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_audit_admin_created", "admin_audit_log", ["admin_id", "created_at"]
    )
    op.create_index(
        "ix_audit_target", "admin_audit_log", ["target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_target", table_name="admin_audit_log")
    op.drop_index("ix_audit_admin_created", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
