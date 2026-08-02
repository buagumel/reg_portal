from models import db, Course, Department


def list_courses(search=None, department_id=None, level=None, semester_id=None,
                  min_credits=None, max_credits=None, status=None, page=1, per_page=20, sort='code'):
    query = Course.query
    if search:
        like = f'%{search}%'
        query = query.filter(
            (Course.code.ilike(like)) | (Course.title.ilike(like)) | (Course.description.ilike(like))
        )
    if department_id:
        query = query.filter(Course.department_id == department_id)
    if level:
        query = query.filter(Course.level == level)
    if semester_id:
        query = query.filter(Course.semester_id == semester_id)
    if min_credits is not None:
        query = query.filter(Course.credits >= min_credits)
    if max_credits is not None:
        query = query.filter(Course.credits <= max_credits)
    if status:
        query = query.filter(Course.status == status)

    sort_columns = {'code': Course.code, 'title': Course.title, 'credits': Course.credits, 'status': Course.status}
    query = query.order_by(sort_columns.get(sort, Course.code))

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_course(course_id):
    return Course.query.get_or_404(course_id)


def create_course(code, title, credits, department_id, level, course_type, academic_session_id, semester_id,
                   description=None, instructor=None, schedule=None, max_capacity=None):
    department = Department.query.get(department_id)
    course = Course(
        code=code, title=title, credits=credits,
        department=department.name if department else '', department_id=department_id,
        level=level or None, course_type=course_type,
        academic_session_id=academic_session_id, semester_id=semester_id,
        description=description or None, instructor=instructor or None, schedule=schedule or None,
        max_capacity=max_capacity, status='active',
    )
    db.session.add(course)
    db.session.commit()
    return course


def update_course(course_id, **fields):
    course = get_course(course_id)
    if fields.get('department_id'):
        department = Department.query.get(fields['department_id'])
        if department:
            fields['department'] = department.name
    for key, value in fields.items():
        setattr(course, key, value)
    db.session.commit()
    return course


def set_course_status(course_id, status):
    course = get_course(course_id)
    course.status = status
    db.session.commit()
    return course
