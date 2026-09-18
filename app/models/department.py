from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.time import utc_now
from app.models.base import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("name", name="departments_name_key"),
        UniqueConstraint("code", name="departments_code_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    default_workweek: Mapped[list[str]] = mapped_column("workweek", JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    users = relationship("User", back_populates="department")
    shift_templates = relationship(
        "ShiftTemplate", secondary="department_shifts", back_populates="departments"
    )
    department_roster_days = relationship("DepartmentRosterDay", back_populates="department")

    @property
    def workweek(self) -> list[str]:
        return self.default_workweek

    @workweek.setter
    def workweek(self, value: list[str]) -> None:
        self.default_workweek = value

    @property
    def shifts(self):
        return self.shift_templates
