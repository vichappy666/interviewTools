"""init users / balance_ledger / admins / auth_throttle + admin seed

Revision ID: 0001
Revises:
Create Date: 2026-04-29
"""
import bcrypt
import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------- users -------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("balance_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default="1"),
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
    )

    # ------- balance_ledger -------
    op.create_table(
        "balance_ledger",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("delta_seconds", sa.Integer, nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "recharge",
                "session",
                "admin_grant",
                "admin_revoke",
                "refund",
                name="ledger_reason",
            ),
            nullable=False,
        ),
        sa.Column("ref_type", sa.String(32), nullable=True),
        sa.Column("ref_id", sa.BigInteger, nullable=True),
        sa.Column("balance_after", sa.Integer, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ledger_user_created", "balance_ledger", ["user_id", "created_at"]
    )

    # ------- admins -------
    op.create_table(
        "admins",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ------- auth_throttle -------
    op.create_table(
        "auth_throttle",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(80), nullable=False, unique=True),
        sa.Column("count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reset_at", sa.DateTime(timezone=False), nullable=False),
    )

    # ------- seed default admin (admin / admin) -------
    pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt(rounds=12)).decode()
    op.bulk_insert(
        sa.table(
            "admins",
            sa.column("username", sa.String),
            sa.column("password_hash", sa.String),
        ),
        [{"username": "admin", "password_hash": pw_hash}],
    )


def downgrade() -> None:
    op.drop_table("auth_throttle")
    op.drop_table("admins")
    op.drop_index("ix_ledger_user_created", table_name="balance_ledger")
    op.drop_table("balance_ledger")
    op.drop_table("users")
