"""replace salary scale with direct employee salary

Revision ID: 0058_direct_employee_salary
Revises: 0057_training_date_required
Create Date: 2026-04-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0058_direct_employee_salary"
down_revision = "0057_training_date_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("monthly_salary", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_monthly_salary_nonnegative",
        "users",
        "monthly_salary IS NULL OR monthly_salary >= 0",
    )

    # Preserve the current computed amount before removing the scale inputs.
    op.execute(
        """
        UPDATE users AS u
        SET monthly_salary = ROUND(
            s.minimum_wage_amount
            * POWER(
                s.basic_salary_multiplier,
                GREATEST(
                    COALESCE(p.salary_grade, 1)
                    + COALESCE(u.rank_level, 1)
                    - 2,
                    0
                )
            )
            * POWER(
                s.basic_salary_step_multiplier,
                GREATEST(COALESCE(u.step_number, 1) - 1, 0)
            ),
            2
        )
        FROM positions AS p
        CROSS JOIN LATERAL (
            SELECT
                minimum_wage_amount,
                basic_salary_multiplier,
                basic_salary_step_multiplier
            FROM payroll_settings
            ORDER BY id
            LIMIT 1
        ) AS s
        WHERE u.position_id = p.id
          AND u.monthly_salary IS NULL
        """
    )
    op.execute(
        """
        UPDATE users AS u
        SET monthly_salary = latest.salary
        FROM (
            SELECT DISTINCT ON (user_id)
                user_id,
                salary
            FROM payslips
            WHERE salary IS NOT NULL
            ORDER BY user_id, year DESC NULLS LAST, month DESC NULLS LAST,
                     period DESC NULLS LAST, id DESC
        ) AS latest
        WHERE u.id = latest.user_id
          AND u.monthly_salary IS NULL
        """
    )

    op.create_table(
        "user_salary_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("change_reason", sa.String(length=500), nullable=True),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "monthly_salary >= 0",
            name="ck_user_salary_assignments_monthly_salary_nonnegative",
        ),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_salary_assignments_id",
        "user_salary_assignments",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_user_salary_assignments_user_id",
        "user_salary_assignments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_salary_assignments_effective_from",
        "user_salary_assignments",
        ["effective_from"],
        unique=False,
    )
    op.create_index(
        "ix_user_salary_assignments_effective_to",
        "user_salary_assignments",
        ["effective_to"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO user_salary_assignments (
            user_id,
            monthly_salary,
            effective_from,
            effective_to,
            change_reason,
            changed_by,
            created_at,
            updated_at
        )
        SELECT
            id,
            monthly_salary,
            COALESCE(date_of_hiring, CURRENT_DATE),
            NULL,
            'Initial migration from salary scale',
            NULL,
            NOW(),
            NOW()
        FROM users
        WHERE monthly_salary IS NOT NULL
        """
    )

    op.drop_constraint("ck_users_rank_level_positive", "users", type_="check")
    op.drop_constraint("ck_users_step_number_positive", "users", type_="check")
    op.drop_constraint(
        "ck_user_position_assignments_rank_level_positive",
        "user_position_assignments",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_position_assignments_step_number_positive",
        "user_position_assignments",
        type_="check",
    )
    op.drop_constraint("ck_users_monthly_salary_nonnegative", "users", type_="check")

    op.drop_column("payroll_settings", "minimum_wage_amount")
    op.drop_column("payroll_settings", "basic_salary_multiplier")
    op.drop_column("payroll_settings", "basic_salary_step_multiplier")
    op.drop_column("payroll_settings", "basic_salary_steps")
    op.drop_column("payroll_settings", "max_position_rank")
    op.drop_column("positions", "salary_grade")
    op.drop_column("users", "rank")
    op.drop_column("users", "rank_level")
    op.drop_column("users", "step_number")
    op.drop_column("payslips", "rank")
    op.drop_column("user_position_assignments", "rank_level")
    op.drop_column("user_position_assignments", "step_number")


def downgrade() -> None:
    op.add_column(
        "payroll_settings",
        sa.Column("minimum_wage_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("basic_salary_multiplier", sa.Numeric(8, 4), nullable=False, server_default="1"),
    )
    op.add_column(
        "payroll_settings",
        sa.Column(
            "basic_salary_step_multiplier",
            sa.Numeric(8, 4),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("basic_salary_steps", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("max_position_rank", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "positions",
        sa.Column("salary_grade", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("users", sa.Column("rank", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("rank_level", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("step_number", sa.Integer(), nullable=True))
    op.add_column("payslips", sa.Column("rank", sa.String(length=500), nullable=True))
    op.add_column(
        "user_position_assignments",
        sa.Column("rank_level", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "user_position_assignments",
        sa.Column("step_number", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_rank_level_positive",
        "users",
        "rank_level IS NULL OR rank_level >= 1",
    )
    op.create_check_constraint(
        "ck_users_step_number_positive",
        "users",
        "step_number IS NULL OR step_number >= 1",
    )
    op.create_check_constraint(
        "ck_user_position_assignments_rank_level_positive",
        "user_position_assignments",
        "rank_level >= 1",
    )
    op.create_check_constraint(
        "ck_user_position_assignments_step_number_positive",
        "user_position_assignments",
        "step_number IS NULL OR step_number >= 1",
    )

    op.drop_index("ix_user_salary_assignments_effective_to", table_name="user_salary_assignments")
    op.drop_index(
        "ix_user_salary_assignments_effective_from",
        table_name="user_salary_assignments",
    )
    op.drop_index("ix_user_salary_assignments_user_id", table_name="user_salary_assignments")
    op.drop_index("ix_user_salary_assignments_id", table_name="user_salary_assignments")
    op.drop_table("user_salary_assignments")
    op.drop_column("users", "monthly_salary")
