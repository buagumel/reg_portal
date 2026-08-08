from models import db, CourseOffering, Course, Department, CourseAssessmentComponent, RegisteredCourse


def list_courses(search=None, department_id=None, level=None, semester_id=None,
                  min_credits=None, max_credits=None, status=None, page=1, per_page=20, sort='code'):
    query = CourseOffering.query
    if search:
        like = f'%{search}%'
        query = query.filter(
            (CourseOffering.code.ilike(like)) | (CourseOffering.title.ilike(like)) | (CourseOffering.description.ilike(like))
        )
    if department_id:
        query = query.filter(CourseOffering.department_id == department_id)
    if level:
        query = query.filter(CourseOffering.level == level)
    if semester_id:
        query = query.filter(CourseOffering.semester_id == semester_id)
    if min_credits is not None:
        query = query.filter(CourseOffering.credits >= min_credits)
    if max_credits is not None:
        query = query.filter(CourseOffering.credits <= max_credits)
    if status:
        query = query.filter(CourseOffering.status == status)

    sort_columns = {'code': CourseOffering.code, 'title': CourseOffering.title, 'credits': CourseOffering.credits, 'status': CourseOffering.status}
    query = query.order_by(sort_columns.get(sort, CourseOffering.code))

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_course(course_id):
    return CourseOffering.query.get_or_404(course_id)


def get_enrollment_count(course_id):
    """Current number of students registered for this course offering. A
    one-line duplicate of services/registration.py's get_course_enrollment_count
    — trivial enough that a shared import isn't worth the cross-module coupling."""
    return RegisteredCourse.query.filter_by(course_id=course_id).count()


def create_course(course_id, department_id, level, academic_session_id, semester_id,
                   instructor=None, schedule=None, max_capacity=None):
    """course_id selects the master Course this offering belongs to — its
    code/title/credits/course_type/description are mirrored into this
    offering's own columns at creation time (dual-write), so every existing
    read path that reads offering.code/.title/etc. keeps working unchanged."""
    master = Course.query.get_or_404(course_id)
    department = Department.query.get(department_id)
    offering = CourseOffering(
        code=master.code, title=master.title, credits=master.credits, course_type=master.course_type,
        description=master.description, course_id=master.id,
        department=department.name if department else '', department_id=department_id,
        level=level or None, academic_session_id=academic_session_id, semester_id=semester_id,
        instructor=instructor or None, schedule=schedule or None,
        max_capacity=max_capacity, status='active',
    )
    db.session.add(offering)
    db.session.commit()
    return offering


def update_course(course_id, **fields):
    """fields may include department_id, level, academic_session_id,
    semester_id, instructor, schedule, max_capacity, and optionally
    'master_course_id' to re-link this offering to a different master
    (which re-mirrors code/title/credits/course_type/description from the
    new master)."""
    offering = get_course(course_id)
    if fields.get('department_id'):
        department = Department.query.get(fields['department_id'])
        if department:
            fields['department'] = department.name
    new_master_id = fields.pop('master_course_id', None)
    if new_master_id and new_master_id != offering.course_id:
        master = Course.query.get_or_404(new_master_id)
        offering.course_id = master.id
        offering.code = master.code
        offering.title = master.title
        offering.credits = master.credits
        offering.course_type = master.course_type
        offering.description = master.description
    for key, value in fields.items():
        setattr(offering, key, value)
    db.session.commit()
    return offering


def set_course_status(course_id, status):
    offering = get_course(course_id)
    offering.status = status
    db.session.commit()
    return offering


def get_course_detail(course_id):
    offering = get_course(course_id)
    assessment_components = CourseAssessmentComponent.query.filter_by(course_id=course_id).all()
    return {'course': offering, 'assessment_components': assessment_components}


def set_assessment_components(course_id, components):
    """components: list of {'name': str, 'weight_percent': int}."""
    CourseAssessmentComponent.query.filter_by(course_id=course_id).delete()
    for comp in components:
        if comp.get('name') and comp.get('weight_percent') is not None:
            db.session.add(CourseAssessmentComponent(
                course_id=course_id, name=comp['name'], weight_percent=comp['weight_percent'],
            ))
    db.session.commit()
