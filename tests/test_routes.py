from fastapi.routing import APIRoute

from app.main import app


def test_core_routes_are_registered():
    paths = {
        route.path
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }

    assert "/departments" in paths
    assert "/users" in paths
    assert "/notifications" in paths
    assert "/app-logs" in paths
    assert "/profile/me" in paths
    assert "/profile/me/photo" in paths
    assert "/attendance/shifts" in paths
    assert "/attendance/device/getrequest" in paths
    assert "/attendance/bridge/users" in paths
    assert "/attendance/bridge/commands/sync-users" in paths
    assert "/attendance/bridge/commands/scan-users" in paths
    assert "/attendance/bridge/commands" in paths
    assert "/attendance/bridge/commands/{command_id}/ack" in paths
    assert "/attendance/bridge/commands/history" in paths
    assert "/attendance/bridge/users/snapshot" in paths
    assert "/attendance/bridge/reconcile" in paths
    assert "/attendance/me/{year}/{month}" in paths
    assert "/attendance/users/{user_id}/{year}/{month}" in paths
    assert "/users/{user_id}/biometric" in paths
    assert "/leave/requests/me" in paths
    assert "/leave/requests/review" in paths
    assert "/attendance/overtime-approvers/me" in paths
    assert "/leave/credits/me" in paths
    assert "/payroll/policy-versions" in paths
    assert "/payroll/policy-versions/seed-ph-baseline" in paths
    assert "/payroll/policy-versions/seed-ph-official-core" in paths
    assert "/payroll/policy-versions/{policy_version_id}" in paths
    assert "/payroll/policy-versions/{policy_version_id}/activate" in paths
    assert "/payroll/policy-versions/{policy_version_id}/rules" in paths
    assert "/payroll/policy-versions/{policy_version_id}/sources" in paths
    assert "/payroll/positions" in paths
    assert "/payroll/payslips" in paths
    assert "/payroll/payslips/{payslip_id}/summary-comparison" in paths
    assert "/payroll/thirteenth-month" in paths
    assert "/performance/questionnaires" in paths
    assert "/performance/user-evaluations" in paths
    assert "/performance/feed" in paths
    assert "/performance/announcements" in paths
    assert "/performance/announcements/{announcement_id}/publish" in paths
    assert "/performance/announcements/{announcement_id}/draft" in paths
    assert "/performance/announcements/{announcement_id}/archive" in paths
    assert "/performance/announcements/{announcement_id}/unarchive" in paths
    assert "/performance/polls" in paths
    assert "/performance/polls/{poll_id}/publish" in paths
    assert "/performance/polls/{poll_id}/close" in paths
    assert "/performance/polls/{poll_id}/archive" in paths
    assert "/performance/polls/{poll_id}/unarchive" in paths
    assert "/performance/polls/{poll_id}/votes" in paths
    assert "/performance/polls/{poll_id}/results" in paths
    assert "/performance/shared-resources" in paths
    assert "/performance/shared-resources/{resource_id}" in paths
    assert "/performance/shared-resources/upload" in paths
    assert "/performance/shared-resources/{resource_id}/download" in paths
    assert "/performance/shared-resources/{resource_id}/shares" in paths
    assert "/performance/shared-resources/{resource_id}/confidential-access" in paths
    assert "/chat/users" in paths
    assert "/chat/conversations/{other_user_id}" in paths
    assert "/chat/messages" in paths
    assert "/reports/catalog" in paths
    assert "/reports/payroll/yearly-expense" in paths
    assert "/reports/payroll/summary" in paths
    assert "/reports/users/demographics/gender" in paths
