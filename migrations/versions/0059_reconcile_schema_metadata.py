"""reconcile schema metadata with the live database

Revision ID: 0059_reconcile_schema_metadata
Revises: 0058_direct_employee_salary
Create Date: 2026-04-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0059_reconcile_schema_metadata"
down_revision = "0058_direct_employee_salary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_attendance_records_punch",
        "attendance_records",
        ["punch"],
        unique=False,
    )
    op.create_index(
        "ix_payslip_variable_compensations_payslip_id",
        "payslip_variable_compensations",
        ["payslip_id"],
        unique=False,
    )
    op.create_index(
        "ix_payslip_variable_deductions_payslip_id",
        "payslip_variable_deductions",
        ["payslip_id"],
        unique=False,
    )
    op.alter_column(
        "payslips",
        "automatic_deduction_schedule",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE payslips "
            "SET automatic_deduction_schedule = 'SECOND_CUTOFF_ONLY' "
            "WHERE automatic_deduction_schedule IS NULL"
        )
    )
    op.alter_column(
        "payslips",
        "automatic_deduction_schedule",
        existing_type=sa.String(length=32),
        existing_nullable=True,
        nullable=False,
    )
    op.drop_index(
        "ix_payslip_variable_deductions_payslip_id",
        table_name="payslip_variable_deductions",
    )
    op.drop_index(
        "ix_payslip_variable_compensations_payslip_id",
        table_name="payslip_variable_compensations",
    )
    op.drop_index("ix_attendance_records_punch", table_name="attendance_records")
