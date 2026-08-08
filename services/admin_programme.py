from models import db, Programme, ProgrammeDepartment, Department, User


def list_programmes(search=None, status=None, page=1, per_page=20):
    query = Programme.query
    if search:
        like = f'%{search}%'
        query = query.filter((Programme.name.ilike(like)) | (Programme.code.ilike(like)))
    if status:
        query = query.filter(Programme.status == status)
    query = query.order_by(Programme.name)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_programme(programme_id):
    return Programme.query.get_or_404(programme_id)


def get_programme_detail(programme_id):
    programme = get_programme(programme_id)
    student_count = User.query.filter_by(programme_id=programme_id).count()
    department_ids = get_programme_department_ids(programme_id)
    departments = Department.query.filter(Department.id.in_(department_ids)).order_by(Department.name).all() if department_ids else []
    return {'programme': programme, 'student_count': student_count, 'departments': departments}


def create_programme(name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None):
    programme = Programme(
        name=name, code=code, program_type=program_type, description=description or None,
        uses_semesters=uses_semesters, uses_terms=uses_terms, duration=duration or None,
    )
    db.session.add(programme)
    db.session.commit()
    return programme


def update_programme(programme_id, name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None):
    programme = get_programme(programme_id)
    programme.name = name
    programme.code = code
    programme.program_type = program_type
    programme.description = description or None
    programme.uses_semesters = uses_semesters
    programme.uses_terms = uses_terms
    programme.duration = duration or None
    db.session.commit()
    return programme


def set_programme_status(programme_id, status):
    programme = get_programme(programme_id)
    programme.status = status
    db.session.commit()
    return programme


def get_programme_department_ids(programme_id):
    rows = ProgrammeDepartment.query.filter_by(programme_id=programme_id).all()
    return [row.department_id for row in rows]


def list_departments_for_programme_checkboxes(programme_id):
    """Departments to render as checkboxes on a Programme's detail page: the
    union of all active departments and any department currently linked to
    this programme, regardless of that department's status. Without this, a
    Department that gets deactivated/archived after being linked would drop
    off the checkbox list entirely, and an unmodified "Save Departments"
    submit would silently delete the link (full delete-then-reinsert below)."""
    linked_ids = get_programme_department_ids(programme_id)
    departments = {d.id: d for d in Department.query.filter_by(status='active')}
    if linked_ids:
        for d in Department.query.filter(Department.id.in_(linked_ids)):
            departments.setdefault(d.id, d)
    return sorted(departments.values(), key=lambda d: d.name)


def set_programme_departments(programme_id, department_ids):
    requested_ids = set(department_ids)
    valid_ids = {d.id for d in Department.query.filter(Department.id.in_(requested_ids)).all()} if requested_ids else set()
    ProgrammeDepartment.query.filter_by(programme_id=programme_id).delete()
    for department_id in valid_ids:
        db.session.add(ProgrammeDepartment(programme_id=programme_id, department_id=department_id))
    db.session.commit()
