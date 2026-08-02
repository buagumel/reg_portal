from models import db, User, Programme, AuditLog


def list_active_programmes():
    return Programme.query.filter_by(status='active').order_by(Programme.name).all()


def list_students(search=None, department_id=None, programme_id=None, level=None, semester=None, status=None,
                   enrolled_from=None, enrolled_to=None, page=1, per_page=20, sort='name'):
    query = User.query
    if search:
        like = f'%{search}%'
        query = query.filter((User.reg_no.ilike(like)) | (User.name.ilike(like)))
    if department_id:
        query = query.filter(User.department_id == department_id)
    if programme_id:
        query = query.filter(User.programme_id == programme_id)
    if level:
        query = query.filter(User.level == level)
    if semester:
        query = query.filter(User.semester == semester)
    if status:
        query = query.filter(User.account_status == status)
    if enrolled_from:
        query = query.filter(User.created_at >= enrolled_from)
    if enrolled_to:
        query = query.filter(User.created_at <= enrolled_to)

    sort_columns = {'name': User.name, 'reg_no': User.reg_no, 'status': User.account_status}
    query = query.order_by(sort_columns.get(sort, User.name))

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_student(student_id):
    return User.query.get_or_404(student_id)


def get_student_profile(student_id):
    from services.registration import get_registration_history
    from services.course_history import get_courses_by_semester
    from services.payment import get_payment_history

    user = get_student(student_id)
    registration_history = get_registration_history(user)
    course_history = get_courses_by_semester(user)
    payment_items, payment_total = get_payment_history(user, per_page=10)
    activity_log = AuditLog.query.filter_by(user_id=student_id).order_by(AuditLog.created_at.desc()).limit(20).all()

    return {
        'user': user, 'registration_history': registration_history, 'course_history': course_history,
        'payment_history': payment_items, 'payment_total': payment_total, 'activity_log': activity_log,
    }


def _generate_temp_password():
    """Generate a random temporary password using a CSPRNG, guaranteed to satisfy the
    existing password-strength policy (8+ chars, upper/lower/digit/special)."""
    import secrets
    import string
    from auth_helpers import validate_password_strength

    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(12))
        if not validate_password_strength(password):
            return password


def create_student(reg_no, name, email=None, phone=None, department_id=None, programme_id=None,
                    level=None, semester=None, session=None, nationality=None, state=None, lga=None,
                    dob=None, gender=None, student_type=None):
    from models import Department, Programme

    department = Department.query.get(department_id) if department_id else None
    programme = Programme.query.get(programme_id) if programme_id else None
    temp_password = _generate_temp_password()

    student = User(
        reg_no=reg_no, name=name, email=email or None, phone=phone or None,
        department=department.name if department else None, department_id=department_id,
        course=programme.name if programme else None, programme_id=programme_id,
        level=level or None, semester=semester or None, session=session or None,
        nationality=nationality or None, state=state or None, lga=lga or None,
        dob=dob, gender=gender or None, student_type=student_type or None,
        first_login=True, onboarding_completed=False, email_verified=False, account_status='active',
    )
    student.set_password(temp_password)
    db.session.add(student)
    db.session.commit()
    return student, temp_password


def update_student(student_id, **fields):
    from models import Department, Programme

    student = get_student(student_id)
    if fields.get('department_id'):
        department = Department.query.get(fields['department_id'])
        if department:
            fields['department'] = department.name
    if fields.get('programme_id'):
        programme = Programme.query.get(fields['programme_id'])
        if programme:
            fields['course'] = programme.name
    for key, value in fields.items():
        setattr(student, key, value)
    db.session.commit()
    return student


def set_account_status(student_id, status):
    student = get_student(student_id)
    student.account_status = status
    db.session.commit()
    return student


def reset_student_password(student_id):
    student = get_student(student_id)
    temp_password = _generate_temp_password()
    student.set_password(temp_password)
    student.first_login = True
    db.session.commit()
    return temp_password


def resend_verification(student_id):
    student = get_student(student_id)
    if not student.email:
        return False, 'Student has no email on file yet — nothing to resend to.'
    return True, None
