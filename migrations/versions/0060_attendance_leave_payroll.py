"""add attendance exception rules, fractional leave, and payroll sources

Revision ID: 0060_attendance_leave_payroll
Revises: 0059_reconcile_schema_metadata
Create Date: 2026-10-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0060_attendance_leave_payroll"
down_revision = "0059_reconcile_schema_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shifts",
        sa.Column("late_grace_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_shifts_late_grace_minutes",
        "shifts",
        "late_grace_minutes >= 0 AND late_grace_minutes <= 240",
    )

    op.add_column(
        "leave_requests",
        sa.Column("duration", sa.String(length=20), nullable=False, server_default="FULL_DAY"),
    )
    op.create_check_constraint(
        "ck_leave_requests_duration",
        "leave_requests",
        "duration IN ('FULL_DAY', 'FIRST_HALF', 'SECOND_HALF')",
    )

    op.alter_column(
        "leave_credits",
        "credits",
        existing_type=sa.Integer(),
        type_=sa.Numeric(8, 2),
        existing_nullable=False,
        postgresql_using="credits::numeric(8,2)",
    )
    op.alter_column(
        "leave_credits",
        "used_credits",
        existing_type=sa.Integer(),
        type_=sa.Numeric(8, 2),
        existing_nullable=False,
        postgresql_using="used_credits::numeric(8,2)",
    )

    op.add_column(
        "payslip_variable_deductions",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="MANUAL"),
    )
    op.add_column(
        "payslip_variable_deductions",
        sa.Column("source_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "payslip_variable_deductions",
        sa.Column("source_type", sa.String(length=40), nullable=True),
    )
    op.create_check_constraint(
        "ck_payslip_variable_deductions_source",
        "payslip_variable_deductions",
        "source IN ('MANUAL', 'ATTENDANCE')",
    )
    op.create_index(
        "ix_payslip_variable_deductions_source",
        "payslip_variable_deductions",
        ["payslip_id", "source"],
        unique=False,
    )
    op.create_index(
        "ix_payslip_variable_deductions_source_date",
        "payslip_variable_deductions",
        ["source_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payslip_variable_deductions_source_date",
        table_name="payslip_variable_deductions",
    )
    op.drop_index(
        "ix_payslip_variable_deductions_source",
        table_name="payslip_variable_deductions",
    )
    op.drop_constraint(
        "ck_payslip_variable_deductions_source",
        "payslip_variable_deductions",
        type_="check",
    )
    op.drop_column("payslip_variable_deductions", "source_type")
    op.drop_column("payslip_variable_deductions", "source_date")
    op.drop_column("payslip_variable_deductions", "source")

    op.alter_column(
        "leave_credits",
        "used_credits",
        existing_type=sa.Numeric(8, 2),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="ROUND(used_credits)::integer",
    )
    op.alter_column(
        "leave_credits",
        "credits",
        existing_type=sa.Numeric(8, 2),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="ROUND(credits)::integer",
    )

    op.drop_constraint("ck_leave_requests_duration", "leave_requests", type_="check")
    op.drop_column("leave_requests", "duration")
    op.drop_constraint("ck_shifts_late_grace_minutes", "shifts", type_="check")
    op.drop_column("shifts", "late_grace_minutes")
