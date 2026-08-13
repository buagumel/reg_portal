from flask import request, jsonify, render_template, redirect, url_for, flash
from flask_login import current_user, login_required

from blueprints.registration import registration_bp
from models import RegisteredCourse, StudentRegistration
from services.registration import (
    get_registration_status_context, register_student, get_registration_history,
    get_active_period, RegistrationError,
    add_course, drop_course, submit_registration, get_add_drop_context, get_effective_add_drop_deadline,
)
from services.course import get_available_courses
from services.course_history import get_courses_by_semester
from services.notification import notify_registration_window_events


@registration_bp.route('/registration')
@login_required
def registration():
    notify_registration_window_events(current_user)
    return render_template(
        'registration.html',
        status=get_registration_status_context(current_user),
        history=get_registration_history(current_user),
    )


@registration_bp.route('/registration/register', methods=['POST'])
@login_required
def registration_register():
    period = get_active_period(current_user)
    if period is None:
        return jsonify({'success': False, 'message': 'No registration period is currently configured.'}), 400

    try:
        reg = register_student(current_user, period)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Registration created. Redirecting to payment...',
        'redirect': url_for('payments.payment_registration_summary', registration_id=reg.id),
    })


@registration_bp.route('/add_drop')
@login_required
def add_drop():
    context = get_add_drop_context(current_user)
    if context['period'] is None or context['student_registration'] is None:
        flash('Please complete semester registration before selecting courses.')
        return redirect(url_for('registration.registration'))
    return render_template('add_drop.html')


@registration_bp.route('/add_drop/data')
@login_required
def add_drop_data():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    available = get_available_courses(current_user, period, student_registration)
    selected = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()
    effective_deadline = get_effective_add_drop_deadline(period, student_registration)

    def course_json(c):
        return {'id': c.id, 'code': c.code, 'title': c.title, 'credits': c.credits, 'type': c.course_type}

    return jsonify({
        'success': True,
        'session': period.academic_session.name,
        'semester': period.semester.name,
        'deadline': effective_deadline.strftime('%d %b %Y'),
        'closes_at_iso': effective_deadline.isoformat(),
        'min_credits': context['min_credits'],
        'max_credits': context['max_credits'],
        'credits_registered': student_registration.credits_registered,
        'courses_submitted': student_registration.courses_submitted,
        'available_courses': [course_json(c) for c in available],
        'selected_courses': [course_json(rc.course) for rc in selected],
    })


@registration_bp.route('/add_drop/add', methods=['POST'])
@login_required
def add_drop_add():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        add_course(current_user, period, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@registration_bp.route('/add_drop/drop', methods=['POST'])
@login_required
def add_drop_drop():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        drop_course(current_user, period, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@registration_bp.route('/add_drop/submit', methods=['POST'])
@login_required
def add_drop_submit():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        submit_registration(current_user, period, student_registration)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'redirect': url_for('registration.my_courses')})


@registration_bp.route('/registration/slip')
@login_required
def registration_slip():
    student_registration = (
        StudentRegistration.query
        .filter_by(user_id=current_user.id, courses_submitted=True)
        .order_by(StudentRegistration.registered_at.desc())
        .first()
    )
    if student_registration is None:
        flash('No submitted registration found to print.')
        return redirect(url_for('registration.registration'))

    courses = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()
    return render_template('registration_slip.html', registration=student_registration, courses=courses)


@registration_bp.route('/my_courses')
@login_required
def my_courses():
    return render_template('my_courses.html', groups=get_courses_by_semester(current_user))


@registration_bp.route('/courses/<int:course_id>/details')
@login_required
def course_details(course_id):
    registered_course = RegisteredCourse.query.join(StudentRegistration).filter(
        RegisteredCourse.course_id == course_id,
        StudentRegistration.user_id == current_user.id,
    ).first()
    if registered_course is None:
        return jsonify({'success': False, 'message': 'Course not found.'}), 404

    course = registered_course.course
    return jsonify({
        'success': True,
        'code': course.code,
        'title': course.title,
        'credits': course.credits,
        'department': course.department,
        'semester': course.semester.name,
        'description': course.description or 'Not available',
        'instructor': course.instructor or 'Not available',
        'schedule': course.schedule or 'Not available',
    })
