from models import db, Course, CourseOffering, CoursePrerequisite, CourseCorequisite


def list_master_courses(search=None, status=None, page=1, per_page=20):
    query = Course.query
    if search:
        like = f'%{search}%'
        query = query.filter((Course.code.ilike(like)) | (Course.title.ilike(like)))
    if status:
        query = query.filter(Course.status == status)
    query = query.order_by(Course.code)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_master_course(course_id):
    return Course.query.get_or_404(course_id)


def get_master_course_detail(course_id):
    course = get_master_course(course_id)
    prerequisites = [cp.prerequisite_course for cp in CoursePrerequisite.query.filter_by(course_id=course_id).all()]
    corequisites = [cc.corequisite_course for cc in CourseCorequisite.query.filter_by(course_id=course_id).all()]
    offerings = CourseOffering.query.filter_by(course_id=course_id).order_by(CourseOffering.id.desc()).all()
    return {
        'course': course, 'prerequisites': prerequisites, 'corequisites': corequisites,
        'offerings': offerings,
    }


def create_master_course(code, title, credits, course_type, description=None):
    course = Course(code=code, title=title, credits=credits, course_type=course_type, description=description or None)
    db.session.add(course)
    db.session.commit()
    return course


def update_master_course(course_id, code, title, credits, course_type, description=None):
    course = get_master_course(course_id)
    course.code = code
    course.title = title
    course.credits = credits
    course.course_type = course_type
    course.description = description or None
    db.session.commit()
    return course


def set_master_course_status(course_id, status):
    course = get_master_course(course_id)
    course.status = status
    db.session.commit()
    return course


def list_master_courses_for_picker(exclude_id=None, include_id=None):
    """include_id: union in this specific Course (regardless of status) if
    it isn't already in the active-only result set — used by the offering
    edit form so an offering's currently-linked master stays selectable even
    after being archived. Without this, an admin resubmitting the offering
    form unchanged would have the browser silently default to the first
    active master, silently re-linking (and re-mirroring catalog fields
    from) the wrong course. Same pattern as sub-project 1's
    list_departments_for_programme_checkboxes and sub-project 2's
    session-Programme-dropdown fix."""
    query = Course.query.filter(Course.status != 'archived')
    if exclude_id:
        query = query.filter(Course.id != exclude_id)
    courses = query.order_by(Course.code).all()
    if include_id and include_id not in {c.id for c in courses}:
        current = Course.query.get(include_id)
        if current:
            courses = sorted(courses + [current], key=lambda c: c.code)
    return courses


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
