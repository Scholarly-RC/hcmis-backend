from typing import Any, cast

import anyio
import app.db.base  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import Mp2Enrollment
from app.repositories.payroll import Mp2EnrollmentRepository


class _EmptyResult:
    def scalars(self) -> "_EmptyResult":
        return self

    def all(self) -> list[Mp2Enrollment]:
        return []


class _CapturingSession:
    statement: Any = None

    async def execute(self, statement: Any) -> _EmptyResult:
        self.statement = statement
        return _EmptyResult()


def test_mp2_list_eager_loads_employee_department() -> None:
    session = _CapturingSession()
    repository = Mp2EnrollmentRepository(cast(AsyncSession, session))

    async def load_enrollments() -> None:
        await repository.list()

    anyio.run(load_enrollments)

    relationship_keys = [
        getattr(element, "key", None)
        for option in session.statement._with_options
        for element in option.path
    ]
    assert "user" in relationship_keys
    assert "department" in relationship_keys
