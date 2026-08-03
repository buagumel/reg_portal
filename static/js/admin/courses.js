import { showToast } from '../shared/toast.js';

const tableBody = document.getElementById('coursesTableBody');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const departmentFilter = document.getElementById('departmentFilter');
const semesterFilter = document.getElementById('semesterFilter');
const statusFilter = document.getElementById('statusFilter');
const paginationInfo = document.getElementById('paginationInfo');
const pageButtons = document.getElementById('pageButtons');

let state = { search: '', department_id: '', semester_id: '', status: '', page: 1, sort: 'code' };

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

function renderRows(courses) {
    if (courses.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);">No courses found.</td></tr>';
        return;
    }
    tableBody.innerHTML = courses.map((c) => `
        <tr>
            <td style="font-family:monospace;"><a href="/admin/courses/${c.id}" style="color: var(--text-main); font-weight:600; text-decoration:none;">${escapeHtml(c.code)}</a></td>
            <td>${escapeHtml(c.title)}</td>
            <td>${escapeHtml(c.department)}</td>
            <td>${escapeHtml(c.level)}</td>
            <td>${escapeHtml(c.semester)}</td>
            <td>${c.credits}</td>
            <td style="text-transform:capitalize;">${escapeHtml(c.status)}</td>
        </tr>
    `).join('');
}

function renderPagination(total, page, perPage) {
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    paginationInfo.textContent = total === 0 ? 'No courses' : `Showing page ${page} of ${totalPages} (${total} total)`;
    pageButtons.innerHTML = '';
    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (i === page ? ' active' : '');
        btn.textContent = i;
        btn.addEventListener('click', () => { state.page = i; load(); });
        pageButtons.appendChild(btn);
    }
}

async function load() {
    tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading…</td></tr>';

    const params = new URLSearchParams({ page: state.page, sort: state.sort });
    if (state.search) params.set('search', state.search);
    if (state.department_id) params.set('department_id', state.department_id);
    if (state.semester_id) params.set('semester_id', state.semester_id);
    if (state.status) params.set('status', state.status);

    const result = await getJson(`/admin/courses/data?${params.toString()}`);
    if (!result.success) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: #b13e3e;">Could not load courses.</td></tr>';
        return;
    }
    renderRows(result.courses);
    renderPagination(result.total, result.page, result.per_page);
}

searchBtn.addEventListener('click', () => { state.search = searchInput.value.trim(); state.page = 1; load(); });
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.search = searchInput.value.trim(); state.page = 1; load(); } });
departmentFilter.addEventListener('change', () => { state.department_id = departmentFilter.value; state.page = 1; load(); });
semesterFilter.addEventListener('change', () => { state.semester_id = semesterFilter.value; state.page = 1; load(); });
statusFilter.addEventListener('change', () => { state.status = statusFilter.value; state.page = 1; load(); });

document.querySelectorAll('[data-sort]').forEach((th) => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => { state.sort = th.dataset.sort; state.page = 1; load(); });
});

load();
