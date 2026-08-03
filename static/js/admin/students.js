import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';

const tableBody = document.getElementById('studentsTableBody');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const departmentFilter = document.getElementById('departmentFilter');
const programmeFilter = document.getElementById('programmeFilter');
const levelFilter = document.getElementById('levelFilter');
const semesterFilter = document.getElementById('semesterFilter');
const statusFilter = document.getElementById('statusFilter');
const enrolledFrom = document.getElementById('enrolledFrom');
const enrolledTo = document.getElementById('enrolledTo');
const paginationInfo = document.getElementById('paginationInfo');
const pageButtons = document.getElementById('pageButtons');
const selectAll = document.getElementById('selectAll');
const bulkBar = document.getElementById('bulkBar');
const bulkCount = document.getElementById('bulkCount');

let state = {
    search: '', department_id: '', programme_id: '', level: '', semester: '', status: '',
    enrolled_from: '', enrolled_to: '', page: 1, sort: 'name',
};

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function getJson(url) {
    const csrf = document.getElementById('csrf_token').value;
    const response = await fetch(url, { headers: { 'X-CSRFToken': csrf } });
    return response.json();
}

function updateBulkBar() {
    const checked = tableBody.querySelectorAll('.row-check:checked');
    if (checked.length === 0) {
        bulkBar.style.display = 'none';
        return;
    }
    bulkBar.style.display = 'flex';
    bulkCount.textContent = `${checked.length} selected`;
}

export function getSelectedIds() {
    return Array.from(tableBody.querySelectorAll('.row-check:checked')).map((cb) => cb.value);
}

function renderRows(students) {
    if (students.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:2rem; color: var(--text-muted);">No students found.</td></tr>';
        return;
    }
    tableBody.innerHTML = students.map((s) => `
        <tr>
            <td style="padding:0.8rem;"><input type="checkbox" class="row-check" value="${s.id}"></td>
            <td style="padding:0.8rem;">${s.profile_picture_url ? `<img src="${s.profile_picture_url}" style="width:32px; height:32px; border-radius:50%; object-fit:cover;">` : '<i class="fas fa-user-circle" style="font-size:1.6rem; color: var(--text-muted);"></i>'}</td>
            <td style="padding:0.8rem; font-family:monospace;"><a href="/admin/students/${s.id}" style="color: var(--text-main); font-weight:600; text-decoration:none;">${escapeHtml(s.reg_no)}</a></td>
            <td style="padding:0.8rem;">${escapeHtml(s.name)}</td>
            <td style="padding:0.8rem;">${escapeHtml(s.department)}</td>
            <td style="padding:0.8rem;">${escapeHtml(s.programme)}</td>
            <td style="padding:0.8rem;">${escapeHtml(s.level)}</td>
            <td style="padding:0.8rem;">${escapeHtml(s.semester)}</td>
            <td style="padding:0.8rem; text-transform:capitalize;">${escapeHtml(s.status)}</td>
        </tr>
    `).join('');

    tableBody.querySelectorAll('.row-check').forEach((cb) => cb.addEventListener('change', updateBulkBar));
    selectAll.checked = false;
    updateBulkBar();
}

function renderPagination(total, page, perPage) {
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    paginationInfo.textContent = total === 0 ? 'No students' : `Showing page ${page} of ${totalPages} (${total} total)`;
    pageButtons.innerHTML = '';
    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (i === page ? ' active' : '');
        btn.textContent = i;
        btn.addEventListener('click', () => { state.page = i; load(); });
        pageButtons.appendChild(btn);
    }
}

export async function load() {
    tableBody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:2rem; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading…</td></tr>';

    const params = new URLSearchParams({ page: state.page, sort: state.sort });
    if (state.search) params.set('search', state.search);
    if (state.department_id) params.set('department_id', state.department_id);
    if (state.programme_id) params.set('programme_id', state.programme_id);
    if (state.level) params.set('level', state.level);
    if (state.semester) params.set('semester', state.semester);
    if (state.status) params.set('status', state.status);
    if (state.enrolled_from) params.set('enrolled_from', state.enrolled_from);
    if (state.enrolled_to) params.set('enrolled_to', state.enrolled_to);

    const result = await getJson(`/admin/students/data?${params.toString()}`);
    if (!result.success) {
        tableBody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:2rem; color: #b13e3e;">Could not load students.</td></tr>';
        return;
    }
    renderRows(result.students);
    renderPagination(result.total, result.page, result.per_page);
}

searchBtn.addEventListener('click', () => { state.search = searchInput.value.trim(); state.page = 1; load(); });
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.search = searchInput.value.trim(); state.page = 1; load(); } });
departmentFilter.addEventListener('change', () => { state.department_id = departmentFilter.value; state.page = 1; load(); });
programmeFilter.addEventListener('change', () => { state.programme_id = programmeFilter.value; state.page = 1; load(); });
levelFilter.addEventListener('change', () => { state.level = levelFilter.value.trim(); state.page = 1; load(); });
semesterFilter.addEventListener('change', () => { state.semester = semesterFilter.value.trim(); state.page = 1; load(); });
statusFilter.addEventListener('change', () => { state.status = statusFilter.value; state.page = 1; load(); });
enrolledFrom.addEventListener('change', () => { state.enrolled_from = enrolledFrom.value; state.page = 1; load(); });
enrolledTo.addEventListener('change', () => { state.enrolled_to = enrolledTo.value; state.page = 1; load(); });

selectAll.addEventListener('change', () => {
    tableBody.querySelectorAll('.row-check').forEach((cb) => { cb.checked = selectAll.checked; });
    updateBulkBar();
});

document.querySelectorAll('[data-sort]').forEach((th) => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => { state.sort = th.dataset.sort; state.page = 1; load(); });
});

const bulkActivateBtn = document.getElementById('bulkActivateBtn');
const bulkSuspendBtn = document.getElementById('bulkSuspendBtn');
const bulkDeactivateBtn = document.getElementById('bulkDeactivateBtn');
const bulkResetPasswordBtn = document.getElementById('bulkResetPasswordBtn');
const bulkResendEmailBtn = document.getElementById('bulkResendEmailBtn');
const bulkDeptSelect = document.getElementById('bulkDeptSelect');
const bulkAssignDeptBtn = document.getElementById('bulkAssignDeptBtn');
const bulkProgSelect = document.getElementById('bulkProgSelect');
const bulkAssignProgBtn = document.getElementById('bulkAssignProgBtn');

async function runBulkStatus(status, label) {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    if (!confirm(`${label} ${ids.length} selected student(s)?`)) return;

    const result = await postJson('/admin/students/bulk-status', { student_ids: ids, status });
    showToast(result.message || (result.success ? 'Updated.' : 'Could not update students.'), !result.success);
    if (result.success) load();
}

bulkActivateBtn.addEventListener('click', () => runBulkStatus('active', 'Activate'));
bulkSuspendBtn.addEventListener('click', () => runBulkStatus('suspended', 'Suspend'));
bulkDeactivateBtn.addEventListener('click', () => runBulkStatus('deactivated', 'Deactivate'));

function downloadCsv(filename, rows) {
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
}

bulkResetPasswordBtn.addEventListener('click', async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    if (!confirm(`Reset passwords for ${ids.length} selected student(s)? This cannot be undone.`)) return;

    const result = await postJson('/admin/students/bulk-reset-password', { student_ids: ids });
    showToast(result.message || (result.success ? 'Passwords reset.' : 'Could not reset passwords.'), !result.success);
    if (result.success) {
        downloadCsv('reset-passwords.csv', [['reg_no', 'temp_password'], ...result.results.map((r) => [r.reg_no, r.temp_password])]);
    }
});

bulkResendEmailBtn.addEventListener('click', async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    if (!confirm(`Resend onboarding email to ${ids.length} selected student(s)?`)) return;

    const result = await postJson('/admin/students/bulk-resend-email', { student_ids: ids });
    showToast(result.message || (result.success ? 'Sent.' : 'Could not send emails.'), !result.success);
});

bulkAssignDeptBtn.addEventListener('click', async () => {
    const ids = getSelectedIds();
    const departmentId = bulkDeptSelect.value;
    if (ids.length === 0 || !departmentId) return;
    if (!confirm(`Assign ${ids.length} selected student(s) to this department?`)) return;

    const result = await postJson('/admin/students/bulk-assign-department', { student_ids: ids, department_id: Number(departmentId) });
    showToast(result.message || (result.success ? 'Assigned.' : 'Could not assign department.'), !result.success);
    if (result.success) load();
});

bulkAssignProgBtn.addEventListener('click', async () => {
    const ids = getSelectedIds();
    const programmeId = bulkProgSelect.value;
    if (ids.length === 0 || !programmeId) return;
    if (!confirm(`Assign ${ids.length} selected student(s) to this programme?`)) return;

    const result = await postJson('/admin/students/bulk-assign-programme', { student_ids: ids, programme_id: Number(programmeId) });
    showToast(result.message || (result.success ? 'Assigned.' : 'Could not assign programme.'), !result.success);
    if (result.success) load();
});

const bulkExportCsvBtn = document.getElementById('bulkExportCsvBtn');
const bulkExportXlsxBtn = document.getElementById('bulkExportXlsxBtn');

async function runBulkExport(format) {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    const csrf = document.getElementById('csrf_token').value;
    const response = await fetch('/admin/students/bulk-export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ student_ids: ids, format }),
    });
    if (!response.ok) {
        showToast('Could not export students.', true);
        return;
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `students.${format}`;
    link.click();
    URL.revokeObjectURL(link.href);
}

bulkExportCsvBtn.addEventListener('click', () => runBulkExport('csv'));
bulkExportXlsxBtn.addEventListener('click', () => runBulkExport('xlsx'));

load();
