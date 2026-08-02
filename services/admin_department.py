from models import db, Department, User, Course
from services.admin_validation import is_department_code_unique


def list_departments(search=None, status=None, page=1, per_page=20):
    query = Department.query
    if search:
        like = f'%{search}%'
        query = query.filter((Department.name.ilike(like)) | (Department.code.ilike(like)))
    if status:
        query = query.filter(Department.status == status)
    query = query.order_by(Department.name)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_department(department_id):
    return Department.query.get_or_404(department_id)


def get_department_detail(department_id):
    department = get_department(department_id)
    student_count = User.query.filter_by(department_id=department_id).count()
    course_count = Course.query.filter_by(department_id=department_id).count()
    return {'department': department, 'student_count': student_count, 'course_count': course_count}


def create_department(name, code, faculty=None, head_name=None):
    department = Department(name=name, code=code, faculty=faculty or None, head_name=head_name or None)
    db.session.add(department)
    db.session.commit()
    return department


def update_department(department_id, name, code, faculty=None, head_name=None):
    department = get_department(department_id)
    department.name = name
    department.code = code
    department.faculty = faculty or None
    department.head_name = head_name or None
    db.session.commit()
    return department


def set_department_status(department_id, status):
    department = get_department(department_id)
    department.status = status
    db.session.commit()
    return department
