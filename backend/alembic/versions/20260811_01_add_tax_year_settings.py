"""add per-financial-year tax settings

Revision ID: 20260811_01
Revises:
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tax_year_settings",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("fy_end_year", sa.Integer(), nullable=False),
        sa.Column("other_income_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_deductions_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("investment_deductions_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("prior_year_capital_losses_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("tax_withheld_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_tax_offsets_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_foreign_tax_offsets_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("medicare_levy_exemption_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("resident_full_year", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("franking_credits_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("other_franked_dividends_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_unfranked_dividends_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_foreign_dividends_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_franking_credits_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("foreign_tax_paid_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_interest_income_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_staking_income_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_non_discount_capital_gains_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_discount_capital_gains_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("other_capital_losses_aud", sa.Numeric(28, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fy_end_year", name="uq_tax_year_settings_user_fy"),
    )
    op.create_index("ix_tax_year_settings_user_id", "tax_year_settings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tax_year_settings_user_id", table_name="tax_year_settings")
    op.drop_table("tax_year_settings")
