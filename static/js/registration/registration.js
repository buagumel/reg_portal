import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

function setupCountdown() {
    const area = document.querySelector('.countdown-area');
    if (!area) return;

    const target = new Date(area.dataset.target).getTime();
    const mode = area.dataset.mode;
    const label = document.getElementById('countdownLabel');

    let timer = null;

    function tick() {
        const diff = target - Date.now();
        if (diff <= 0) {
            label.textContent = mode === 'opens' ? 'Opening now…' : 'Closing now…';
            if (timer !== null) clearInterval(timer);
            return;
        }
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
        const minutes = Math.floor((diff / (1000 * 60)) % 60);
        const seconds = Math.floor((diff / 1000) % 60);
        const verb = mode === 'opens' ? 'Opens in' : 'Closes in';
        label.textContent = `${verb} ${days}d ${hours}h ${minutes}m ${seconds}s`;
    }

    tick();
    timer = setInterval(tick, 1000);
}

function setupRegisterNow() {
    const btn = document.getElementById('registerNowBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!window.confirm('Confirm semester registration? You will be redirected to complete payment.')) {
            return;
        }

        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registering…';

        const result = await postJson('/registration/register', {});

        if (result.success) {
            showToast(result.message || 'Registration created.');
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Registration failed.', true);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });
}

function setupHistoryToggles() {
    document.querySelectorAll('.view-details-toggle').forEach((link) => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const item = link.closest('.reg-item');
            const panel = item.querySelector('.reg-detail-panel');
            const text = link.querySelector('.toggle-text');
            const wasExpanded = !panel.hidden;
            panel.hidden = wasExpanded;
            text.textContent = wasExpanded ? 'View details' : 'Hide details';
        });
    });
}

setupCountdown();
setupRegisterNow();
setupHistoryToggles();
