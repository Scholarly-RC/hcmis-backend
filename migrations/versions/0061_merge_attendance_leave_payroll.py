"""merge the attendance/payroll and thirteenth-month migration heads

Revision ID: 0061_merge_attendance_leave_payroll
Revises: 0060_attendance_leave_payroll, 0060_thirteenth_month_att
Create Date: 2026-10-07 00:00:00.000000
"""


revision = "0061_merge_attendance_leave_payroll"
down_revision = (
    "0060_attendance_leave_payroll",
    "0060_thirteenth_month_att",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
