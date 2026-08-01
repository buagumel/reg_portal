import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';

const form = document.getElementById('verifyCodeForm');
const codeInput = document.getElementById('code');
const verifyBtn = document.getElementById('verifyBtn');

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    verifyBtn.disabled = true;
    verifyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

    const result = await postJson('/admin/verify-reset-code', { code: codeInput.value.trim() });

    if (result.success) {
        window.location.href = result.redirect;
    } else {
        verifyBtn.disabled = false;
        verifyBtn.innerHTML = '<i class="fas fa-check"></i> Verify code';
        showToast(result.message, true);
    }
});
