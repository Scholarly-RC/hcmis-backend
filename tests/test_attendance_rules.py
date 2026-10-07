from datetime import date, datetime, time
from types import SimpleNamespace
from uuid import UUID

from app.core.time import app_timezone
from app.services.attendance_rules import evaluate_attendance_day


def _shift(**overrides):
    values = {
        "start_time": time(8, 0),
        "end_time": time(17, 0),
        "start_time_2": None,
        "end_time_2": None,
        "late_grace_minutes": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _record(record_id: int, clocked_at: datetime, punch: str):
    return SimpleNamespace(
        id=record_id,
        user_id=UUID(int=1),
        timestamp=clocked_at.replace(tzinfo=app_timezone()),
        punch=punch,
    )


def test_grace_period_includes_boundary_and_late_is_proportional():
    selected_date = date(2026, 10, 1)
    boundary = evaluate_attendance_day(
        selected_date=selected_date,
        shift=_shift(late_grace_minutes=10),
        records=[
            _record(1, datetime(2026, 10, 1, 8, 10), "IN"),
            _record(2, datetime(2026, 10, 1, 17, 0), "OUT"),
        ],
        reference_date=selected_date,
    )
    assert boundary.status == "PRESENT"
    assert boundary.late_minutes == 0

    late = evaluate_attendance_day(
        selected_date=selected_date,
        shift=_shift(late_grace_minutes=10),
        records=[
            _record(3, datetime(2026, 10, 1, 8, 11), "IN"),
            _record(4, datetime(2026, 10, 1, 17, 0), "OUT"),
        ],
        reference_date=selected_date,
    )
    assert late.status == "LATE"
    assert late.late_minutes == 1
    assert late.deduction_units > 0


def test_absence_and_partial_punch_have_different_payroll_behavior():
    selected_date = date(2026, 10, 1)
    absent = evaluate_attendance_day(
        selected_date=selected_date,
        shift=_shift(),
        records=[],
        reference_date=date(2026, 10, 2),
    )
    assert absent.status == "ABSENT"
    assert absent.deduction_units == 1

    partial = evaluate_attendance_day(
        selected_date=selected_date,
        shift=_shift(),
        records=[_record(5, datetime(2026, 10, 1, 8, 0), "IN")],
        reference_date=date(2026, 10, 2),
    )
    assert partial.status == "PARTIAL_RECORD"
    assert partial.partial_record is True
    assert partial.deduction_units == 0


def test_split_shift_evaluates_each_session_and_half_day_leave():
    selected_date = date(2026, 10, 1)
    shift = _shift(
        start_time=time(8, 0),
        end_time=time(12, 0),
        start_time_2=time(13, 0),
        end_time_2=time(17, 0),
    )
    split = evaluate_attendance_day(
        selected_date=selected_date,
        shift=shift,
        records=[
            _record(6, datetime(2026, 10, 1, 8, 0), "IN"),
            _record(7, datetime(2026, 10, 1, 12, 0), "OUT"),
            _record(8, datetime(2026, 10, 1, 13, 15), "IN"),
            _record(9, datetime(2026, 10, 1, 17, 0), "OUT"),
        ],
        reference_date=selected_date,
    )
    assert split.status == "LATE"
    assert split.late_minutes == 15

    leave = SimpleNamespace(duration="FIRST_HALF", approval_type="NON_PAID")
    half_leave = evaluate_attendance_day(
        selected_date=selected_date,
        shift=shift,
        records=[
            _record(10, datetime(2026, 10, 1, 13, 0), "IN"),
            _record(11, datetime(2026, 10, 1, 17, 0), "OUT"),
        ],
        approved_leave=leave,
        reference_date=selected_date,
    )
    assert half_leave.status == "ON_UNPAID_LEAVE"
    assert half_leave.deduction_units == 0.5
