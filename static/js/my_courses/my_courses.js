const modal = document.getElementById('courseDetailsModal');

function openModal(data) {
    document.getElementById('modalCourseTitle').innerText = `${data.code} — ${data.title}`;
    document.getElementById('modalCourseCode').innerText = data.code;
    document.getElementById('modalCourseDepartment').innerText = data.department;
    document.getElementById('modalCourseCredits').innerText = data.credits;
    document.getElementById('modalCourseSemester').innerText = data.semester;
    document.getElementById('modalCourseInstructor').innerText = data.instructor;
    document.getElementById('modalCourseSchedule').innerText = data.schedule;
    document.getElementById('modalCourseDescription').innerText = data.description;
    modal.hidden = false;
}

document.querySelectorAll('.view-details-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const courseId = btn.dataset.courseId;
        const resp = await fetch(`/courses/${courseId}/details`);
        const data = await resp.json();
        if (!data.success) return;
        openModal(data);
    });
});

document.getElementById('courseModalClose').addEventListener('click', () => { modal.hidden = true; });
modal.addEventListener('click', (e) => { if (e.target === modal) modal.hidden = true; });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') modal.hidden = true; });
