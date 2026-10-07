"""store attendance deductions in 13th month payouts

Revision ID: 0060_thirteenth_month_att
Revises: 0059_reconcile_schema_metadata
Create Date: 2026-10-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0060_thirteenth_month_att"
down_revision = "0059_reconcile_schema_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column_name in (
        "annual_basic_salary",
        "annual_absence_deductions",
        "annual_late_deductions",
        "annual_undertime_deductions",
        "eligible_basic_salary",
    ):
        op.add_column(
            "thirteenth_month_payouts",
            sa.Column(
                column_name,
                sa.Numeric(12, 2),
                nullable=False,
                server_default=sa.text("0.00"),
            ),
        )

    op.execute(
        """
        UPDATE thirteenth_month_payouts
        SET annual_basic_salary = gross_amount * 12,
            eligible_basic_salary = gross_amount * 12
        """
    )

    for column_name in (
        "annual_basic_salary",
        "annual_absence_deductions",
        "annual_late_deductions",
        "annual_undertime_deductions",
        "eligible_basic_salary",
    ):
        op.alter_column(
            "thirteenth_month_payouts",
            column_name,
            server_default=None,
        )


def downgrade() -> None:
    for column_name in (
        "eligible_basic_salary",
        "annual_undertime_deductions",
        "annual_late_deductions",
        "annual_absence_deductions",
        "annual_basic_salary",
    ):
        op.drop_column("thirteenth_month_payouts", column_name)
