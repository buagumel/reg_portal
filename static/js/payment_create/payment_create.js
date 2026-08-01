import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const checkboxes = document.querySelectorAll('.category-checkbox');
const summaryList = document.getElementById('summaryList');
const summaryTotal = document.getElementById('summaryTotal');
const proceedBtn = document.getElementById('proceedBtn');

function formatNaira(amount) {
    return '₦' + amount.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderSummary() {
    const selected = Array.from(checkboxes).filter((cb) => cb.checked);

    if (selected.length === 0) {
        summaryList.innerHTML = '<li class="summary-empty">No items selected yet.</li>';
        summaryTotal.textContent = formatNaira(0);
        proceedBtn.disabled = true;
        return;
    }

    let total = 0;
    summaryList.innerHTML = '';
    selected.forEach((cb) => {
        const amount = parseFloat(cb.dataset.amount);
        total += amount;
        const li = document.createElement('li');
        li.textContent = '';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = cb.dataset.name;
        const amountSpan = document.createElement('span');
        amountSpan.textContent = formatNaira(amount);
        li.appendChild(nameSpan);
        li.appendChild(amountSpan);
        summaryList.appendChild(li);
    });
    summaryTotal.textContent = formatNaira(total);
    proceedBtn.disabled = false;
}

checkboxes.forEach((cb) => cb.addEventListener('change', renderSummary));

if (proceedBtn) {
    proceedBtn.addEventListener('click', async () => {
        const selected = Array.from(checkboxes).filter((cb) => cb.checked);
        if (selected.length === 0) return;

        proceedBtn.disabled = true;
        const originalHtml = proceedBtn.innerHTML;
        proceedBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Redirecting to Remita…';

        const idempotencyKey = document.getElementById('idempotencyKey').value;
        const items = selected.map((cb) => ({ category_id: parseInt(cb.dataset.id, 10), quantity: 1 }));

        const result = await postJson('/payment/create', { idempotency_key: idempotencyKey, items });

        if (result.success) {
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Could not start payment.', true);
            proceedBtn.disabled = false;
            proceedBtn.innerHTML = originalHtml;
        }
    });
}
