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
