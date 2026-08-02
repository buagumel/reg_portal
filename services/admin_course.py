from models import db, Course, Department, CoursePrerequisite, CourseCorequisite, CourseAssessmentComponent


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


def get_course_detail(course_id):
    course = get_course(course_id)
    prerequisites = [cp.prerequisite_course for cp in CoursePrerequisite.query.filter_by(course_id=course_id).all()]
    corequisites = [cc.corequisite_course for cc in CourseCorequisite.query.filter_by(course_id=course_id).all()]
    assessment_components = CourseAssessmentComponent.query.filter_by(course_id=course_id).all()
    return {
        'course': course, 'prerequisites': prerequisites, 'corequisites': corequisites,
        'assessment_components': assessment_components,
    }


def list_courses_for_picker(exclude_id=None):
    query = Course.query.filter(Course.status != 'archived')
    if exclude_id:
        query = query.filter(Course.id != exclude_id)
    return query.order_by(Course.code).all()


def set_prerequisites(course_id, prerequisite_course_ids):
    CoursePrerequisite.query.filter_by(course_id=course_id).delete()
    for prereq_id in prerequisite_course_ids:
        if prereq_id != course_id:
            db.session.add(CoursePrerequisite(course_id=course_id, prerequisite_course_id=prereq_id))
    db.session.commit()


def set_corequisites(course_id, corequisite_course_ids):
    CourseCorequisite.query.filter_by(course_id=course_id).delete()
    for coreq_id in corequisite_course_ids:
        if coreq_id != course_id:
            db.session.add(CourseCorequisite(course_id=course_id, corequisite_course_id=coreq_id))
    db.session.commit()


def set_assessment_components(course_id, components):
    """components: list of {'name': str, 'weight_percent': int}."""
    CourseAssessmentComponent.query.filter_by(course_id=course_id).delete()
    for comp in components:
        if comp.get('name') and comp.get('weight_percent') is not None:
            db.session.add(CourseAssessmentComponent(
                course_id=course_id, name=comp['name'], weight_percent=comp['weight_percent'],
            ))
    db.session.commit()
