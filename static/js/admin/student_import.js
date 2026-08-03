import { postForm } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const fileInput = document.getElementById('fileInput');
const previewBtn = document.getElementById('previewBtn');
const confirmBtn = document.getElementById('confirmBtn');
const previewResult = document.getElementById('previewResult');

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function enableConfirm() {
    confirmBtn.disabled = false;
    confirmBtn.style.opacity = '1';
}

function disableConfirm() {
    confirmBtn.disabled = true;
    confirmBtn.style.opacity = '0.5';
}

previewBtn.addEventListener('click', async () => {
    if (!fileInput.files.length) {
        showToast('Choose a CSV file first.', true);
        return;
    }
    disableConfirm();
    previewResult.innerHTML = '<p style="color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Validating…</p>';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    const result = await postForm('/admin/students/import/preview', formData);

    if (!result.success) {
        previewResult.innerHTML = `<p style="color: var(--danger);">${escapeHtml(result.message || 'Could not validate file.')}</p>`;
        return;
    }

    const rowsHtml = result.flagged_rows.length === 0
        ? '<p style="color: var(--success);">No issues found — every row is ready to import.</p>'
        : `<table style="width:100%; border-collapse:collapse; margin-top:0.8rem;">
            <thead><tr style="text-align:left; border-bottom:1px solid var(--border-color);"><th style="padding:0.5rem;">Row</th><th style="padding:0.5rem;">Reason</th></tr></thead>
            <tbody>${result.flagged_rows.map((r) => `<tr style="border-bottom:1px solid var(--border-color);"><td style="padding:0.5rem;">${r.row_number}</td><td style="padding:0.5rem; color: var(--danger);">${escapeHtml(r.reason)}</td></tr>`).join('')}</tbody>
          </table>`;

    previewResult.innerHTML = `
        <div style="display:flex; gap:1.5rem; flex-wrap:wrap; padding:1rem; background: var(--bg-body); border-radius:0.6rem;">
            <div><div style="font-weight:700; color: var(--success);">${result.valid_count}</div><div style="font-size:0.8rem; color: var(--text-muted);">Ready to import</div></div>
            <div><div style="font-weight:700; color: var(--warning);">${result.duplicate_count}</div><div style="font-size:0.8rem; color: var(--text-muted);">Duplicates</div></div>
            <div><div style="font-weight:700; color: var(--danger);">${result.error_count}</div><div style="font-size:0.8rem; color: var(--text-muted);">Errors</div></div>
            <div><div style="font-weight:700;">${result.total_rows}</div><div style="font-size:0.8rem; color: var(--text-muted);">Total rows</div></div>
        </div>
        ${rowsHtml}
    `;

    if (result.valid_count > 0) {
        enableConfirm();
    } else {
        showToast('No valid rows to import.', true);
    }
});

fileInput.addEventListener('change', () => {
    disableConfirm();
    previewResult.innerHTML = '';
});
