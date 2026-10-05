from app.models.user import User


CAP_ACCESS_HR_WORKSPACE = "access_hr_workspace"
CAP_VIEW_PAYROLL_SUMMARY = "view_payroll_summary"


def normalize_role(value: str | None) -> str:
    return (value or "").strip().upper()


def is_staff_user(user: User) -> bool:
    return bool(user.is_superuser or is_hr_user(user))


def is_hr_user(user: User) -> bool:
    return normalize_role(user.role) == "HR"


def resolve_user_capabilities(user: User) -> list[str]:
    capabilities = {
        "view_dashboard_home",
        "view_profile_self",
        "edit_profile_self",
        "view_attendance_self",
        "manage_leave_self",
        "view_payslips_self",
        "view_performance_self",
    }

    if is_staff_user(user):
        capabilities.update(
            {
                CAP_ACCESS_HR_WORKSPACE,
                "manage_hr_users",
                "manage_shift_templates",
                "manage_attendance_records",
                "manage_overtime_requests",
                "manage_leave_requests",
                "manage_salary_structure",
                "manage_payroll_settings",
                "manage_payslips",
                "manage_announcements_polls",
                "manage_shared_resources",
                "view_reports",
                "view_app_logs",
            }
        )

    if is_hr_user(user):
        capabilities.add(CAP_VIEW_PAYROLL_SUMMARY)

    if user.can_modify_shift:
        capabilities.add("manage_shift_templates")

    return sorted(capabilities)
