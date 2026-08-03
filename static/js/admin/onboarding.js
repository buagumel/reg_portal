const departmentFilter = document.getElementById('departmentFilter');
const programmeFilter = document.getElementById('programmeFilter');
const sessionFilter = document.getElementById('sessionFilter');

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function load() {
    const params = new URLSearchParams();
    if (departmentFilter.value) params.set('department_id', departmentFilter.value);
    if (programmeFilter.value) params.set('programme_id', programmeFilter.value);
    if (sessionFilter.value.trim()) params.set('session', sessionFilter.value.trim());

    const response = await fetch(`/admin/onboarding/data?${params.toString()}`);
    const result = await response.json();
    if (!result.success) return;

    document.getElementById('bNotLoggedIn').textContent = result.not_logged_in;
    document.getElementById('bPasswordNotChanged').textContent = result.password_not_changed;
    document.getElementById('bProfileIncomplete').textContent = result.profile_incomplete;
    document.getElementById('bEmailNotVerified').textContent = result.email_not_verified;
    document.getElementById('bCompleted').textContent = result.onboarding_completed;
    document.getElementById('completionRate').textContent = `${result.completion_percentage}% (${result.onboarding_completed} of ${result.total})`;
    document.getElementById('avgCompletionTime').textContent = result.analytics.average_completion_hours !== null
        ? `${result.analytics.average_completion_hours} hours`
        : 'Not enough data yet';

    const byDeptList = document.getElementById('byDepartmentList');
    byDeptList.innerHTML = result.analytics.completion_by_department.length === 0
        ? '<li style="color: var(--text-muted);">No data yet.</li>'
        : result.analytics.completion_by_department.map((row) => `<li style="padding:0.4rem 0; border-bottom:1px solid var(--border-color);">${escapeHtml(row.department)}: <strong>${row.count}</strong></li>`).join('');

    const bySessionList = document.getElementById('bySessionList');
    bySessionList.innerHTML = result.analytics.completion_by_session.length === 0
        ? '<li style="color: var(--text-muted);">No data yet.</li>'
        : result.analytics.completion_by_session.map((row) => `<li style="padding:0.4rem 0; border-bottom:1px solid var(--border-color);">${escapeHtml(row.session)}: <strong>${row.count}</strong></li>`).join('');
}

departmentFilter.addEventListener('change', load);
programmeFilter.addEventListener('change', load);
sessionFilter.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });

load();
