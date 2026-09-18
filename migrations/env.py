import asyncio
from logging.config import fileConfig
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.base import Base
from app.models.department import Department  # noqa: F401
from app.models.leave import LeaveCredit  # noqa: F401
from app.models.leave import LeaveRequest  # noqa: F401
from app.models.chat import Message  # noqa: F401
from app.models.performance import Evaluation  # noqa: F401
from app.models.performance import Questionnaire  # noqa: F401
from app.models.performance import UserEvaluation  # noqa: F401
from app.models.payroll import FixedCompensation  # noqa: F401
from app.models.payroll import Position  # noqa: F401
from app.models.payroll import Mp2Enrollment  # noqa: F401
from app.models.payroll import PayrollSetting  # noqa: F401
from app.models.payroll import Payslip  # noqa: F401
from app.models.payroll import PayslipVariableCompensation  # noqa: F401
from app.models.payroll import PayslipVariableDeduction  # noqa: F401
from app.models.payroll import ThirteenthMonthAdjustment  # noqa: F401
from app.models.payroll import ThirteenthMonthPayout  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.special_requests import CertificateAttendanceRequest  # noqa: F401
from app.models.special_requests import OfficialBusinessRequest  # noqa: F401
from app.models.training import Training  # noqa: F401
from app.models.training import TrainingParticipant  # noqa: F401
from app.models.training import TrainingParticipantAttachment  # noqa: F401
from app.models.user import User, UserSalaryAssignment  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    def do_run_migrations(sync_connection) -> None:
        context.configure(
            connection=sync_connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

    async def run_async_migrations() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

        await connectable.dispose()

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
