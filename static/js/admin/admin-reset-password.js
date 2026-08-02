import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';
import { checkPasswordRules, isPasswordValid } from '../shared/validation.js';

const form = document.getElementById('resetPasswordForm');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const submitBtn = document.getElementById('submitBtn');
const rulesList = document.getElementById('passwordRules');

function updateRuleChecklist() {
    const results = checkPasswordRules(newPasswordInput.value);
    results.forEach(({ key, met }) => {
        const item = rulesList.querySelector(`[data-rule="${key}"]`);
        if (item) item.classList.toggle('met', met);
    });
}

newPasswordInput.addEventListener('input', updateRuleChecklist);

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (!isPasswordValid(newPassword)) {
        showToast('Password does not meet all requirements', true);
        return;
    }
    if (newPassword !== confirmPassword) {
        showToast('Passwords do not match', true);
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/admin/reset-password', { new: newPassword, confirm: confirmPassword });

    if (result.success) {
        showToast(result.message, false);
        window.location.href = result.redirect;
    } else {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-check"></i> Reset password';
        showToast(result.message, true);
    }
});
