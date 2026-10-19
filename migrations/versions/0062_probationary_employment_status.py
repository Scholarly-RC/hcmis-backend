"""correct probationary employment status spelling

Revision ID: 0062_probationary_employment_status
Revises: 0061_merge_att_leave_payroll
Create Date: 2026-10-19 00:00:00.000000
"""

from alembic import op


revision = "0062_probationary_emp_status"
down_revision = "0061_merge_att_leave_payroll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET employment_status = 'PROBATIONARY'
        WHERE employment_status = 'PROVISIONARY'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET employment_status = 'PROVISIONARY'
        WHERE employment_status = 'PROBATIONARY'
        """
    )
