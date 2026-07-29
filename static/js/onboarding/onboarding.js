import { showToast } from '../shared/toast.js';
import { postJson, postForm } from '../shared/api.js';
import { isValidEmail } from '../shared/validation.js';
import { Stepper } from '../shared/stepper.js';
import { createOtpController } from './otp.js';

export const collected = { email: '', phone: '', address: '', pictureFile: null };

const FIELD_ERROR_IDS = {
    email: 'infoEmailError',
    phone: 'infoPhoneError',
    address: 'infoAddressError',
    profile_picture: 'infoPictureError',
};

let otpController;

export const stepper = new Stepper({
    steps: ['info', 'otp', 'review'],
    container: document.querySelector('.onboarding-wrap'),
    onStepChange: (step) => {
        if (step === 'otp') otpController.onEnter();
    },
});

otpController = createOtpController({
    getEmail: () => collected.email,
    onVerified: () => {
        renderReview();
        stepper.next();
    },
    onBack: () => stepper.back(),
});

// ---- Step 1: Student Info ----
const infoForm = document.getElementById('infoForm');
const infoNextBtn = document.getElementById('infoNextBtn');
const pictureInput = document.getElementById('infoPicture');
const picturePreview = document.getElementById('picturePreview');

pictureInput.addEventListener('change', () => {
    const file = pictureInput.files[0];
    if (!file) { picturePreview.style.display = 'none'; return; }
    picturePreview.src = URL.createObjectURL(file);
    picturePreview.style.display = 'block';
});

function clearFieldErrors() {
    ['infoEmailError', 'infoPhoneError', 'infoAddressError', 'infoPictureError'].forEach((id) => {
        document.getElementById(id).textContent = '';
    });
}

infoForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearFieldErrors();

    const email = document.getElementById('infoEmail').value.trim();
    const phone = document.getElementById('infoPhone').value.trim();
    const address = document.getElementById('infoAddress').value.trim();
    const pictureFile = pictureInput.files[0];

    let hasError = false;
    if (!email || !isValidEmail(email)) {
        document.getElementById('infoEmailError').textContent = 'Enter a valid email address';
        hasError = true;
    }
    if (!phone) {
        document.getElementById('infoPhoneError').textContent = 'Phone number is required';
        hasError = true;
    }
    if (!address) {
        document.getElementById('infoAddressError').textContent = 'Address is required';
        hasError = true;
    }
    if (!pictureFile) {
        document.getElementById('infoPictureError').textContent = 'Profile picture is required';
        hasError = true;
    }
    if (hasError) return;

    infoNextBtn.disabled = true;
    infoNextBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const formData = new FormData();
    formData.append('email', email);
    formData.append('phone', phone);
    formData.append('address', address);
    formData.append('profile_picture', pictureFile);

    const result = await postForm('/onboarding/save-info', formData);

    infoNextBtn.disabled = false;
    infoNextBtn.innerHTML = 'Next <i class="fas fa-arrow-right"></i>';

    if (!result.success) {
        if (result.errors) {
            Object.entries(result.errors).forEach(([field, msg]) => {
                const el = document.getElementById(FIELD_ERROR_IDS[field]);
                if (el) el.textContent = msg;
            });
        }
        showToast(result.message, true);
        return;
    }

    collected.email = email;
    collected.phone = phone;
    collected.address = address;
    collected.pictureFile = pictureFile;

    stepper.next();
});

// ---- Step 3: Review & Confirm ----
function renderReview() {
    const grid = document.getElementById('reviewGrid');
    grid.innerHTML = `
        <div class="review-item"><label>Email</label><span>${collected.email}</span></div>
        <div class="review-item"><label>Phone</label><span>${collected.phone}</span></div>
        <div class="review-item"><label>Address</label><span>${collected.address}</span></div>
        <div class="review-item"><label>Profile Picture</label><span>${collected.pictureFile ? collected.pictureFile.name : ''}</span></div>
    `;
}

document.getElementById('reviewEditBtn').addEventListener('click', () => stepper.goTo('info'));

document.getElementById('reviewConfirmBtn').addEventListener('click', async () => {
    const btn = document.getElementById('reviewConfirmBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/onboarding/complete', {});

    if (result.success) {
        showToast('Welcome! Your profile is complete.', false);
        window.location.href = result.redirect;
    } else {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check"></i> Confirm & Save';
        showToast(result.message, true);
    }
});

stepper.init();
