import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const tableBody = document.getElementById('paymentsTableBody');
const filterTabs = document.getElementById('filterTabs');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const dateFrom = document.getElementById('dateFrom');
const dateTo = document.getElementById('dateTo');
const paginationInfo = document.getElementById('paginationInfo');
const pageButtons = document.getElementById('pageButtons');

const STATUS_LABELS = {
    successful: '<span class="status-badge paid"><i class="fas fa-check-circle"></i> Paid</span>',
    pending: '<span class="status-badge pending"><i class="fas fa-hourglass-half"></i> Pending</span>',
    cancelled: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Cancelled</span>',
    failed: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Failed</span>',
    timeout: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Timed out</span>',
};

let state = { status: '', search: '', page: 1 };

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

function renderActions(p) {
    const actions = [];
    if (p.has_receipt) {
        actions.push(`<a href="/payment/${p.reference}/receipt" class="receipt-link"><i class="fas fa-eye"></i> View</a>`);
        actions.push(`<a href="/payment/${p.reference}/receipt.pdf" class="receipt-link"><i class="fas fa-file-pdf"></i> PDF</a>`);
        actions.push(`<button class="receipt-link resend-btn" data-reference="${p.reference}"><i class="fas fa-envelope"></i> Resend</button>`);
    }
    if (p.can_resume) {
        actions.push(`<a href="/payment/${p.reference}/resume" class="receipt-link"><i class="fas fa-play"></i> Resume</a>`);
    }
    if (p.can_retry) {
        actions.push(`<button class="receipt-link retry-btn" data-reference="${p.reference}"><i class="fas fa-redo"></i> Retry</button>`);
    }
    return actions.join(' ');
}

function renderRows(payments) {
    if (payments.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);">No payments found.</td></tr>';
        return;
    }
    tableBody.innerHTML = payments.map((p) => `
        <tr>
            <td><strong>${escapeHtml(p.description)}</strong></td>
            <td>${escapeHtml(p.date)}</td>
            <td>${escapeHtml(p.session)} ${escapeHtml(p.semester)}</td>
            <td style="font-family: monospace;">${escapeHtml(p.reference)}</td>
            <td><strong>${p.amount.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</strong></td>
            <td>${STATUS_LABELS[p.status] || escapeHtml(p.status)}</td>
            <td>${renderActions(p)}</td>
        </tr>
    `).join('');

    tableBody.querySelectorAll('.retry-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const result = await postJson(`/payment/${btn.dataset.reference}/retry`, {});
            showToast(result.success ? `Status: ${result.status}` : (result.message || 'Retry failed.'), !result.success);
            load();
        });
    });
    tableBody.querySelectorAll('.resend-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const result = await postJson(`/payment/${btn.dataset.reference}/resend-receipt`, {});
            showToast(result.message || (result.success ? 'Receipt sent.' : 'Could not resend receipt.'), !result.success);
            btn.disabled = false;
        });
    });
}

function renderPagination(total, page, perPage) {
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    paginationInfo.textContent = total === 0 ? 'No transactions' : `Showing page ${page} of ${totalPages} (${total} total)`;
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

    const params = new URLSearchParams({ page: state.page });
    if (state.status) params.set('status', state.status);
    if (state.search) params.set('search', state.search);
    if (dateFrom.value) params.set('date_from', dateFrom.value);
    if (dateTo.value) params.set('date_to', dateTo.value);

    const result = await getJson(`/payments_history/data?${params.toString()}`);
    if (!result.success) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: #b13e3e;">Could not load payment history.</td></tr>';
        return;
    }

    document.getElementById('summaryTotal').textContent = result.summary.total;
    document.getElementById('summaryAmountPaid').textContent = '₦' + result.summary.total_amount_paid.toLocaleString('en-NG', { minimumFractionDigits: 2 });
    document.getElementById('summaryPending').textContent = result.summary.pending;
    document.getElementById('summaryCancelled').textContent = result.summary.cancelled;

    renderRows(result.payments);
    renderPagination(result.total, result.page, result.per_page);
}

filterTabs.querySelectorAll('.filter-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        filterTabs.querySelectorAll('.filter-tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        state.status = tab.dataset.status;
        state.page = 1;
        load();
    });
});

searchBtn.addEventListener('click', () => { state.search = searchInput.value.trim(); state.page = 1; load(); });
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.search = searchInput.value.trim(); state.page = 1; load(); } });
dateFrom.addEventListener('change', () => { state.page = 1; load(); });
dateTo.addEventListener('change', () => { state.page = 1; load(); });

load();
