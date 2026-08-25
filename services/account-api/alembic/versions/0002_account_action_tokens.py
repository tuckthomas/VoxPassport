"""account action tokens

Revision ID: 0002_account_action_tokens
Revises: 0001_accounts
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_account_action_tokens"
down_revision = "0001_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_action_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')",
            name="ck_account_action_tokens_purpose",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_account_action_tokens_user_id", "account_action_tokens", ["user_id"], unique=False)
    op.create_index("ix_account_action_tokens_purpose", "account_action_tokens", ["purpose"], unique=False)
    op.create_index("ix_account_action_tokens_token_hash", "account_action_tokens", ["token_hash"], unique=True)
    op.create_index("ix_account_action_tokens_expires_at", "account_action_tokens", ["expires_at"], unique=False)
    op.create_index("ix_account_action_tokens_consumed_at", "account_action_tokens", ["consumed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_account_action_tokens_consumed_at", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_expires_at", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_token_hash", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_purpose", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_user_id", table_name="account_action_tokens")
    op.drop_table("account_action_tokens")
