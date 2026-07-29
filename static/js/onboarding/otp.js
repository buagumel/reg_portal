import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';

const OTP_DURATION_SECONDS = 300;

export function createOtpController({ getEmail, onVerified, onBack }) {
    const codeInput = document.getElementById('otpCode');
    const errorEl = document.getElementById('otpError');
    const timerEl = document.getElementById('otpTimer');
    const resendBtn = document.getElementById('resendOtpBtn');
    const verifyBtn = document.getElementById('otpVerifyBtn');
    const backBtn = document.getElementById('otpBackBtn');
    const emailTarget = document.getElementById('otpEmailTarget');

    let countdownHandle = null;
    let secondsLeft = 0;
    let hasSentOnce = false;

    function formatTime(total) {
        const m = Math.floor(total / 60);
        const s = total % 60;
        return `${m}:${String(s).padStart(2, '0')}`;
    }

    function startCountdown() {
        clearInterval(countdownHandle);
        secondsLeft = OTP_DURATION_SECONDS;
        resendBtn.disabled = true;
        timerEl.textContent = `Code expires in ${formatTime(secondsLeft)}`;
        countdownHandle = setInterval(() => {
            secondsLeft -= 1;
            if (secondsLeft <= 0) {
                clearInterval(countdownHandle);
                timerEl.textContent = 'Code expired';
                resendBtn.disabled = false;
                return;
            }
            timerEl.textContent = `Code expires in ${formatTime(secondsLeft)}`;
        }, 1000);
    }

    async function sendCode() {
        errorEl.textContent = '';
        resendBtn.disabled = true;
        resendBtn.textContent = 'Sending...';

        const result = await postJson('/send-email-code', { new_email: getEmail() });

        resendBtn.textContent = 'Resend code';

        if (result.success) {
            emailTarget.textContent = getEmail();
            codeInput.value = '';
            startCountdown();
            showToast('Verification code sent', false);
        } else {
            errorEl.textContent = result.message;
            resendBtn.disabled = false;
        }
    }

    resendBtn.addEventListener('click', sendCode);

    backBtn.addEventListener('click', () => {
        clearInterval(countdownHandle);
        onBack();
    });

    verifyBtn.addEventListener('click', async () => {
        errorEl.textContent = '';
        const code = codeInput.value.trim();
        if (!code) {
            errorEl.textContent = 'Enter the code sent to your email';
            return;
        }

        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

        const result = await postJson('/verify-email-code', { code, new_email: getEmail() });

        verifyBtn.disabled = false;
        verifyBtn.innerHTML = 'Verify <i class="fas fa-arrow-right"></i>';

        if (result.success) {
            clearInterval(countdownHandle);
            onVerified();
            return;
        }

        errorEl.textContent = result.message;
        if (result.max_attempts_reached) {
            resendBtn.disabled = false;
            codeInput.value = '';
        }
    });

    return {
        onEnter() {
            if (!hasSentOnce) {
                hasSentOnce = true;
                sendCode();
            }
        },
    };
}
