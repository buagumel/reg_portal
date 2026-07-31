import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

let allCourses = [];
let registeredCourses = [];
let currentFilter = 'all';
let searchTerm = '';
let MIN_CREDITS = 0;
let MAX_CREDITS = 0;
let coursesSubmitted = false;

function getTotalCredits() {
    return registeredCourses.reduce((sum, c) => sum + c.credits, 0);
}

function getTypeClass(type) { return type === 'core' ? 'type-core' : type === 'elective' ? 'type-elective' : 'type-lab'; }
function getTypeLabel(type) { return type === 'core' ? 'Core' : type === 'elective' ? 'Elective' : 'Lab'; }

function updateUI() {
    const total = getTotalCredits();
    document.getElementById('totalCredits').innerText = total;
    const percentage = MAX_CREDITS ? (total / MAX_CREDITS) * 100 : 0;
    document.getElementById('creditProgressBar').style.width = Math.min(percentage, 100) + '%';
    document.getElementById('registeredCount').innerText = registeredCourses.length;

    const warningDiv = document.getElementById('creditWarning');
    if (total < MIN_CREDITS) {
        warningDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Need ${MIN_CREDITS - total} more credits (min ${MIN_CREDITS})`;
        warningDiv.style.color = '#b45b1c';
    } else if (total > MAX_CREDITS) {
        warningDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Exceeds max by ${total - MAX_CREDITS}`;
        warningDiv.style.color = '#b13e3e';
    } else {
        warningDiv.innerHTML = `<i class="fas fa-check-circle"></i> Within credit limits`;
        warningDiv.style.color = '#0f7b4e';
    }

    const registeredBody = document.getElementById('registeredTableBody');
    if (registeredCourses.length === 0) {
        registeredBody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:1.5rem; color:#5a7b99;">No courses registered yet</td></tr>';
    } else {
        registeredBody.innerHTML = registeredCourses.map(c => `
            <tr>
                <td><strong>${c.code}</strong></td>
                <td>${c.title}</td>
                <td><span class="credit-badge">${c.credits} cr</span></td>
                <td>${coursesSubmitted ? '' : `<button class="remove-btn" data-course-id="${c.id}" title="Drop"><i class="fas fa-trash-alt"></i></button>`}</td>
            </tr>
        `).join('');
        registeredBody.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', () => dropCourse(Number(btn.dataset.courseId)));
        });
    }

    renderAvailableCourses();

    const submitBtn = document.querySelector('.action-buttons .btn-primary');
    const resetBtn = document.querySelector('.action-buttons .btn-secondary');
    if (submitBtn) submitBtn.disabled = coursesSubmitted;
    if (resetBtn) resetBtn.disabled = coursesSubmitted;
}

function renderAvailableCourses() {
    const tbody = document.getElementById('coursesTableBody');
    if (coursesSubmitted) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:1.5rem; color:#5a7b99;">Course selection has been submitted</td></tr>';
        return;
    }

    const filtered = allCourses.filter(course => {
        const matchesFilter = currentFilter === 'all' || course.type === currentFilter;
        const matchesSearch = course.code.toLowerCase().includes(searchTerm) || course.title.toLowerCase().includes(searchTerm);
        return matchesFilter && matchesSearch;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:1.5rem; color:#5a7b99;">No courses available</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(course => `
        <tr>
            <td><strong>${course.code}</strong></td>
            <td>${course.title}</td>
            <td><span class="credit-badge">${course.credits} cr</span></td>
            <td><span class="type-badge ${getTypeClass(course.type)}">${getTypeLabel(course.type)}</span></td>
            <td><button class="add-btn" data-course-id="${course.id}"><i class="fas fa-plus-circle"></i> Add</button></td>
        </tr>
    `).join('');
    tbody.querySelectorAll('.add-btn').forEach(btn => {
        btn.addEventListener('click', () => addCourse(Number(btn.dataset.courseId)));
    });
}

async function loadData() {
    const resp = await fetch('/add_drop/data');
    const data = await resp.json();
    if (!data.success) {
        showToast(data.message || 'Failed to load registration data', true);
        return;
    }
    MIN_CREDITS = data.min_credits;
    MAX_CREDITS = data.max_credits;
    coursesSubmitted = data.courses_submitted;
    allCourses = data.available_courses;
    registeredCourses = data.selected_courses;

    document.getElementById('deadlineValue').innerText = data.deadline;
    document.getElementById('minCreditsValue').innerText = MIN_CREDITS;
    document.getElementById('maxCreditsValue').innerText = MAX_CREDITS;
    document.getElementById('maxCreditsInline').innerText = MAX_CREDITS;

    updateUI();
}

async function addCourse(courseId) {
    const result = await postJson('/add_drop/add', { course_id: courseId });
    if (!result.success) {
        showToast(result.message || 'Failed to add course', true);
        return;
    }
    await loadData();
    showToast('Course added');
}

async function dropCourse(courseId) {
    const result = await postJson('/add_drop/drop', { course_id: courseId });
    if (!result.success) {
        showToast(result.message || 'Failed to drop course', true);
        return;
    }
    await loadData();
    showToast('Course removed');
}

async function resetRegistration() {
    if (registeredCourses.length === 0 || coursesSubmitted) return;
    if (!confirm('Clear all registered courses?')) return;
    for (const c of [...registeredCourses]) {
        await postJson('/add_drop/drop', { course_id: c.id });
    }
    await loadData();
    showToast('Registration reset');
}

async function submitRegistration() {
    const result = await postJson('/add_drop/submit', {});
    if (!result.success) {
        showToast(result.message || 'Failed to submit registration', true);
        return;
    }
    showToast('Registration submitted');
    window.open('/registration/slip', '_blank');
    setTimeout(() => { window.location.href = result.redirect; }, 1200);
}

document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        renderAvailableCourses();
    });
});

document.getElementById('searchCourse').addEventListener('input', (e) => {
    searchTerm = e.target.value.toLowerCase();
    renderAvailableCourses();
});

document.querySelector('.action-buttons .btn-secondary').addEventListener('click', resetRegistration);
document.querySelector('.action-buttons .btn-primary').addEventListener('click', submitRegistration);

loadData();
