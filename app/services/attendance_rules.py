"""Shared attendance evaluation rules used by summaries, reports, and payroll.

The evaluator is deliberately independent from the database.  That keeps the
business rules testable and ensures that a status shown to HR is the same
status used when a draft payslip is recalculated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from app.core.time import app_timezone, local_today, to_local


FULL_DAY = "FULL_DAY"
FIRST_HALF = "FIRST_HALF"
SECOND_HALF = "SECOND_HALF"


@dataclass(frozen=True)
class AttendanceSession:
    label: str
    start: datetime
    end: datetime

    @property
    def scheduled_minutes(self) -> int:
        return max(int((self.end - self.start).total_seconds() // 60), 0)


@dataclass(frozen=True)
class AttendanceEvaluation:
    status: str
    late_minutes: int = 0
    scheduled_minutes: int = 0
    absence_units: Decimal = Decimal("0.00")
    leave_units: Decimal = Decimal("0.00")
    late_units: Decimal = Decimal("0.00")
    deduction_units: Decimal = Decimal("0.00")
    partial_record: bool = False
    leave_status: str | None = None


def _combine(selected_date: date, selected_time: time) -> datetime:
    return datetime.combine(selected_date, selected_time, tzinfo=app_timezone())


def _window(selected_date: date, start_time: time, end_time: time, label: str) -> AttendanceSession:
    start = _combine(selected_date, start_time)
    end = _combine(selected_date, end_time)
    if end <= start:
        end += timedelta(days=1)
    return AttendanceSession(label=label, start=start, end=end)


def shift_sessions(selected_date: date, shift: Any | None) -> list[AttendanceSession]:
    if shift is None:
        return []

    values = [
        (getattr(shift, "start_time", None), getattr(shift, "end_time", None), "FIRST"),
        (getattr(shift, "start_time_2", None), getattr(shift, "end_time_2", None), "SECOND"),
    ]
    sessions: list[AttendanceSession] = []
    for start_time, end_time, label in values:
        if start_time is not None and end_time is not None:
            sessions.append(_window(selected_date, start_time, end_time, label))
    return sessions


def _half_day_sessions(
    selected_date: date,
    sessions: list[AttendanceSession],
    duration: str,
) -> tuple[list[AttendanceSession], Decimal]:
    if duration == FULL_DAY or not sessions:
        return sessions, Decimal("0.00")

    if len(sessions) == 1:
        session = sessions[0]
        midpoint = session.start + (session.end - session.start) / 2
        if duration == FIRST_HALF:
            return [AttendanceSession(session.label, midpoint, session.end)], Decimal("0.50")
        return [AttendanceSession(session.label, session.start, midpoint)], Decimal("0.50")

    excused_index = 0 if duration == FIRST_HALF else len(sessions) - 1
    excused = sessions[excused_index]
    active = [item for index, item in enumerate(sessions) if index != excused_index]
    full_minutes = sum(item.scheduled_minutes for item in sessions)
    leave_units = (
        Decimal(excused.scheduled_minutes) / Decimal(full_minutes)
        if full_minutes
        else Decimal("0.50")
    )
    return active, leave_units


def _record_timestamp(record: Any) -> datetime:
    return to_local(record.timestamp)


def _records_for_session(
    session: AttendanceSession,
    records: list[Any],
) -> list[Any]:
    # A small tolerance allows an early arrival or an end-of-shift punch while
    # keeping adjacent split-shift sessions from claiming one another's punches.
    tolerance = timedelta(minutes=30)
    return [
        record
        for record in records
        if session.start - tolerance <= _record_timestamp(record) <= session.end + tolerance
    ]


def evaluate_attendance_day(
    *,
    selected_date: date,
    shift: Any | None,
    records: list[Any],
    is_holiday: bool = False,
    approved_leave: Any | None = None,
    reference_date: date | None = None,
) -> AttendanceEvaluation:
    """Evaluate one scheduled date.

    Partial punches intentionally produce no automatic deduction.  A human can
    correct the record and the next draft-payslip sync will recalculate it.
    """

    sessions = shift_sessions(selected_date, shift)
    if not sessions:
        return AttendanceEvaluation(status="NO_SHIFT")
    if is_holiday:
        return AttendanceEvaluation(status="HOLIDAY")

    duration = (getattr(approved_leave, "duration", None) or FULL_DAY) if approved_leave else FULL_DAY
    approval_type = getattr(approved_leave, "approval_type", None) if approved_leave else None
    active_sessions, leave_units = _half_day_sessions(selected_date, sessions, duration)
    leave_is_unpaid = approved_leave is not None and approval_type == "NON_PAID"
    leave_status = None
    if approved_leave is not None:
        leave_status = "ON_UNPAID_LEAVE" if leave_is_unpaid else "ON_PAID_LEAVE"

    full_minutes = sum(item.scheduled_minutes for item in sessions)
    scheduled_minutes = sum(item.scheduled_minutes for item in active_sessions)
    if approved_leave is not None and duration == FULL_DAY:
        return AttendanceEvaluation(
            status=leave_status or "ON_LEAVE",
            scheduled_minutes=0,
            leave_units=Decimal("1.00") if leave_is_unpaid else Decimal("0.00"),
            deduction_units=Decimal("1.00") if leave_is_unpaid else Decimal("0.00"),
            leave_status=leave_status,
        )

    if not active_sessions:
        return AttendanceEvaluation(
            status=leave_status or "ON_LEAVE",
            leave_units=leave_units if leave_is_unpaid else Decimal("0.00"),
            deduction_units=leave_units if leave_is_unpaid else Decimal("0.00"),
            leave_status=leave_status,
        )

    matched_ids: set[int] = set()
    late_minutes = 0
    absence_units = Decimal("0.00")
    late_units = Decimal("0.00")
    partial = False
    missing = False
    grace_minutes = max(int(getattr(shift, "late_grace_minutes", 0) or 0), 0)

    for session in active_sessions:
        candidates = sorted(_records_for_session(session, records), key=_record_timestamp)
        clock_in = next(
            (record for record in candidates if record.punch == "IN" and record.id not in matched_ids),
            None,
        )
        clock_out = None
        if clock_in is not None:
            clock_out = next(
                (
                    record
                    for record in candidates
                    if record.punch == "OUT"
                    and record.id not in matched_ids
                    and _record_timestamp(record) >= _record_timestamp(clock_in)
                ),
                None,
            )
        if clock_in is None or clock_out is None:
            if candidates:
                partial = True
            else:
                missing = True
                if full_minutes:
                    absence_units += Decimal(session.scheduled_minutes) / Decimal(full_minutes)
            continue

        matched_ids.add(clock_in.id)
        matched_ids.add(clock_out.id)
        late_delta = _record_timestamp(clock_in) - session.start - timedelta(minutes=grace_minutes)
        if late_delta.total_seconds() > 0:
            minutes = int(late_delta.total_seconds() // 60)
            late_minutes += minutes
            if session.scheduled_minutes:
                # Split shifts are evaluated independently.  A late arrival
                # consumes the same proportional share of the scheduled
                # session, with the whole-date late cap applied below.
                late_units += Decimal(minutes) / Decimal(session.scheduled_minutes)

    # Any punch that falls in an active session but was not paired is a review
    # case.  Do not turn it into an absence/late deduction automatically.
    if any(
        record.id not in matched_ids
        and any(record in _records_for_session(session, records) for session in active_sessions)
        for record in records
    ):
        partial = True

    if partial:
        return AttendanceEvaluation(
            status="PARTIAL_RECORD",
            late_minutes=late_minutes,
            scheduled_minutes=scheduled_minutes,
            partial_record=True,
            leave_status=leave_status,
        )

    reference = reference_date or local_today()
    is_past = selected_date < reference
    if missing and not is_past:
        status = "PENDING"
    elif missing:
        status = "ABSENT"
    elif late_minutes > 0:
        status = "LATE"
    elif leave_status is not None:
        status = leave_status
    else:
        status = "PRESENT"

    unpaid_leave_units = leave_units if leave_is_unpaid else Decimal("0.00")
    capped_late_units = min(late_units, Decimal("0.50"))
    total_units = min(
        absence_units + unpaid_leave_units + capped_late_units,
        Decimal("1.00"),
    )
    return AttendanceEvaluation(
        status=status,
        late_minutes=late_minutes,
        scheduled_minutes=scheduled_minutes,
        absence_units=absence_units,
        leave_units=unpaid_leave_units,
        late_units=capped_late_units,
        deduction_units=total_units,
        leave_status=leave_status,
    )
