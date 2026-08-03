const periodSelect = document.getElementById('periodSelect');
const departmentFilter = document.getElementById('departmentFilter');
const programmeFilter = document.getElementById('programmeFilter');
const levelFilter = document.getElementById('levelFilter');
const statusFilter = document.getElementById('statusFilter');

let countdownInterval = null;

function formatCountdown(totalSeconds) {
    if (totalSeconds <= 0) return 'Closed';
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    return `${days}d ${hours}h ${minutes}m`;
}

function startCountdown(secondsRemaining) {
    if (countdownInterval) clearInterval(countdownInterval);
    let remaining = secondsRemaining;
    const el = document.getElementById('mCountdown');
    el.textContent = formatCountdown(remaining);
    countdownInterval = setInterval(() => {
        remaining = Math.max(0, remaining - 1);
        el.textContent = formatCountdown(remaining);
        if (remaining <= 0) clearInterval(countdownInterval);
    }, 1000);
}

async function load() {
    const params = new URLSearchParams({ period_id: periodSelect.value });
    if (departmentFilter.value) params.set('department_id', departmentFilter.value);
    if (programmeFilter.value) params.set('programme_id', programmeFilter.value);
    if (levelFilter.value.trim()) params.set('level', levelFilter.value.trim());
    if (statusFilter.value) params.set('status', statusFilter.value);

    const response = await fetch(`/admin/registration/oversight/data?${params.toString()}`);
    const result = await response.json();
    if (!result.success) return;

    document.getElementById('mTotalEligible').textContent = result.total_eligible;
    document.getElementById('mRegistered').textContent = result.registered_count;
    document.getElementById('mPending').textContent = result.pending_count;
    document.getElementById('mIncomplete').textContent = result.incomplete_count;
    document.getElementById('mCompletion').textContent = `${result.completion_percentage}%`;
    document.getElementById('mCredits').textContent = result.total_credits;
    startCountdown(result.seconds_remaining);
}

periodSelect.addEventListener('change', load);
departmentFilter.addEventListener('change', load);
programmeFilter.addEventListener('change', load);
levelFilter.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
statusFilter.addEventListener('change', load);

load();
