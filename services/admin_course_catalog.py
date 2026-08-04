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


def list_master_courses_for_picker(exclude_id=None):
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
