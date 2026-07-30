import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

function setupCountdown() {
    const area = document.querySelector('.countdown-area');
    if (!area) return;

    const target = new Date(area.dataset.target).getTime();
    const mode = area.dataset.mode;
    const label = document.getElementById('countdownLabel');

    function tick() {
        const diff = target - Date.now();
        if (diff <= 0) {
            label.textContent = mode === 'opens' ? 'Opening now…' : 'Closing now…';
            clearInterval(timer);
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
    const timer = setInterval(tick, 1000);
}

function renderRegisteredCard(section, registration) {
    section.innerHTML = `
        <h3><i class="fas fa-hourglass-half"></i> Registration Status</h3>
        <div class="ongoing-card registered-card">
            <div class="card-content">
                <div class="ongoing-info">
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered</div>
                    <h2>${registration.session} ${registration.semester}</h2>
                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-receipt"></i> Ref: ${registration.payment_reference}</span>
                        <span class="detail-item"><i class="fas fa-calendar-check"></i> Registered: ${registration.registered_at}</span>
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Payment: Paid</span>
                    </div>
                    <p class="course-selection-note"><i class="fas fa-info-circle"></i> Course selection will open separately once available.</p>
                </div>
            </div>
        </div>
    `;
}

function setupRegisterNow() {
    const btn = document.getElementById('registerNowBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!window.confirm('Confirm semester registration? This will simulate a successful payment for development purposes.')) {
            return;
        }

        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registering…';

        const result = await postJson('/registration/register', {});

        if (result.success) {
            showToast(result.message || 'Registration successful.');
            const section = document.getElementById('registrationCardSection');
            renderRegisteredCard(section, result.registration);
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
            const expanded = !panel.hidden;
            panel.hidden = expanded;
            text.textContent = expanded ? 'View details' : 'Hide details';
        });
    });
}

setupCountdown();
setupRegisterNow();
setupHistoryToggles();
