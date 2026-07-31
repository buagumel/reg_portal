import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

let currentQuickFilter = 'all';

function buildParams() {
    const params = new URLSearchParams();
    if (currentQuickFilter === 'unread') params.set('read_status', 'unread');
    if (currentQuickFilter === 'archived') params.set('archived', 'true');
    const category = document.getElementById('categoryFilter').value;
    if (category) params.set('category', category);
    const priority = document.getElementById('priorityFilter').value;
    if (priority) params.set('priority', priority);
    const dateFrom = document.getElementById('dateFromFilter').value;
    if (dateFrom) params.set('date_from', dateFrom);
    const dateTo = document.getElementById('dateToFilter').value;
    if (dateTo) params.set('date_to', dateTo);
    const search = document.getElementById('searchInput').value.trim();
    if (search) params.set('search', search);
    return params;
}

function categoryLabel(c) { return c.charAt(0).toUpperCase() + c.slice(1); }
function priorityLabel(p) { return p.charAt(0).toUpperCase() + p.slice(1); }

function renderNotification(n) {
    return `
        <div class="notification-item priority-${n.priority}" data-id="${n.id}">
            <div class="notification-icon"><i class="fas fa-bell"></i></div>
            <div class="notification-content">
                <div class="notification-header">
                    <div class="notification-title">${n.title} ${!n.is_read ? '<span class="unread-badge">New</span>' : ''}</div>
                    <div class="notification-date"><i class="far fa-clock"></i> ${n.created_at}</div>
                </div>
                <div class="notification-meta">
                    <span class="notification-category"><i class="fas fa-tag"></i> ${categoryLabel(n.category)}</span>
                    <span><i class="fas fa-flag"></i> ${priorityLabel(n.priority)} priority</span>
                </div>
                <div class="notification-message">${n.message}</div>
                <div class="notification-footer">
                    ${n.related_url ? `<a href="${n.related_url}" class="action-link">View <i class="fas fa-arrow-right"></i></a>` : ''}
                    <button class="dismiss-btn toggle-read-btn" data-id="${n.id}" data-read="${n.is_read}">
                        <i class="fas fa-${n.is_read ? 'envelope' : 'envelope-open'}"></i> ${n.is_read ? 'Mark unread' : 'Mark read'}
                    </button>
                    <button class="dismiss-btn archive-btn" data-id="${n.id}"><i class="fas fa-archive"></i> Archive</button>
                    <button class="dismiss-btn delete-btn" data-id="${n.id}"><i class="fas fa-times"></i> Delete</button>
                </div>
            </div>
        </div>
    `;
}

function updateSummary(summary) {
    document.getElementById('summaryTotal').innerText = summary.total;
    document.getElementById('summaryUnread').innerText = summary.unread;
    document.getElementById('summaryRead').innerText = summary.read;
    document.getElementById('summaryArchived').innerText = summary.archived;
}

function attachRowListeners() {
    document.querySelectorAll('.toggle-read-btn').forEach(btn => {
        btn.addEventListener('click', () => toggleRead(btn.dataset.id, btn.dataset.read === 'true'));
    });
    document.querySelectorAll('.archive-btn').forEach(btn => {
        btn.addEventListener('click', () => archiveOne(btn.dataset.id));
    });
    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteOne(btn.dataset.id));
    });
}

async function loadData() {
    const params = buildParams();
    const resp = await fetch(`/notifications/data?${params.toString()}`);
    const data = await resp.json();
    if (!data.success) {
        showToast('Failed to load notifications', true);
        return;
    }
    const list = document.getElementById('notificationsList');
    if (data.notifications.length === 0) {
        list.innerHTML = '<div class="empty-state"><i class="far fa-bell-slash"></i><p>No notifications match this filter.</p></div>';
    } else {
        list.innerHTML = data.notifications.map(renderNotification).join('');
    }
    attachRowListeners();
    updateSummary(data.summary);
}

async function toggleRead(id, isRead) {
    const endpoint = isRead ? 'unread' : 'read';
    const result = await postJson(`/notifications/${id}/${endpoint}`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    await loadData();
}

async function archiveOne(id) {
    const result = await postJson(`/notifications/${id}/archive`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('Notification archived');
    await loadData();
}

async function deleteOne(id) {
    const result = await postJson(`/notifications/${id}/delete`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('Notification deleted');
    await loadData();
}

async function markAllRead() {
    const result = await postJson('/notifications/mark-all-read', {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('All notifications marked as read');
    await loadData();
}

document.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentQuickFilter = tab.dataset.value;
        loadData();
    });
});

document.getElementById('categoryFilter').addEventListener('change', loadData);
document.getElementById('priorityFilter').addEventListener('change', loadData);
document.getElementById('dateFromFilter').addEventListener('change', loadData);
document.getElementById('dateToFilter').addEventListener('change', loadData);

let searchDebounceHandle = null;
document.getElementById('searchInput').addEventListener('input', () => {
    clearTimeout(searchDebounceHandle);
    searchDebounceHandle = setTimeout(loadData, 300);
});

document.getElementById('markAllReadBtn').addEventListener('click', markAllRead);

attachRowListeners();
