"""create sessions + session_qa tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-29
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


# revision identifiers
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------- sessions -------
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "total_seconds",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "end_reason",
            sa.Enum(
                "user_stop",
                "balance_zero",
                "idle_timeout",
                "admin_force",
                "error",
                name="session_end_reason",
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "ended", name="session_status"),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index(
        "ix_sessions_user_status", "sessions", ["user_id", "status"]
    )
    op.create_index(
        "ix_sessions_user_started", "sessions", ["user_id", "started_at"]
    )

    # ------- session_qa -------
    op.create_table(
        "session_qa",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.BigInteger,
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column(
            "answer_key_points",
            sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "answer_script",
            sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "answer_full",
            sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "asked_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "source",
            sa.Enum("detected", "manual", name="session_qa_source"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_session_qa_session_asked", "session_qa", ["session_id", "asked_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_session_qa_session_asked", table_name="session_qa")
    op.drop_table("session_qa")
    op.drop_index("ix_sessions_user_started", table_name="sessions")
    op.drop_index("ix_sessions_user_status", table_name="sessions")
    op.drop_table("sessions")
