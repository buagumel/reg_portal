import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const btn = document.getElementById('payNowBtn');
if (btn) {
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Redirecting to Remita…';

        const reference = btn.dataset.reference;
        const result = await postJson(`/payment/${reference}/initiate`, {});

        if (result.success) {
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Could not start payment.', true);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });
}
