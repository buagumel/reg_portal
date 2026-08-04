# DDD Refactor Sub-project 1: Programme↔Department Foundation Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-04

## Context

This is sub-project 1 of 5 in the Programme-centered DDD academic architecture refactor (see `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` for the full audit and decomposition). `Programme` and `Department` currently exist as two unrelated tables (both added in Phase 2). This sub-project makes them related and gives admins a UI to manage that relationship — the foundation everything else in the refactor depends on.

## Goal

Relate `Programme` and `Department` via a many-to-many junction, give `Programme` the fields needed to describe its calendar shape, and build a Programme Management admin module mirroring the existing Departments module. `AcademicSession`, `Course`, `RegistrationPeriod`, and eligibility logic are explicitly untouched here — those are later sub-projects.

## Data model changes

### `Programme` — new columns

- `uses_semesters` (Boolean, `default=True`, `nullable=False`, `server_default='1'`)
- `uses_terms` (Boolean, `default=False`, `nullable=False`, `server_default='0'`)
- `duration` (String(50), nullable — free text, e.g. "2 years")

Migration backfill: all 5 existing seeded Programmes (CIFS, INTLDIP, ADVDIP, ND, HND) get `uses_semesters=True`, `uses_terms=False` at migration time. This is a deliberate simplification, not an inference from `program_type` — the existing seed descriptions for the international programmes ("First or Second Semester") don't cleanly match the term-based example in the refactor request ("Term 1/2/3"), so guessing per-programme term counts now risks silently misconfiguring real data. These flags don't drive any behavior until sub-project 2 (Academic Calendar) reads them — admins can correct them via the new UI at any time before then with no functional effect yet.

### New `ProgrammeDepartment` table

```python
class ProgrammeDepartment(db.Model):
    __tablename__ = 'programme_departments'
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('programme_id', 'department_id'),)

    programme = db.relationship('Programme', backref='programme_departments')
    department = db.relationship('Department', backref='programme_departments')
```

### Migration backfill for `ProgrammeDepartment` rows

Best-effort seed: for every `User` row with both `department_id` and `programme_id` already set (non-null), create the corresponding `ProgrammeDepartment` link if it doesn't already exist. This mirrors the Phase 2 Department backfill precedent. It will not be exhaustive — most historical data predates the FK dual-write — and is documented as a starting point for admins to complete via the UI, not an authoritative source.

## Services — new `services/admin_programme.py`

- `list_programmes(search=None, status=None, page=1, per_page=20)` — filtered, paginated list, signature mirrors `list_departments(search=None, status=None, page=1, per_page=20)` in `services/admin_department.py:5` (filters on `name`/`code` via `ilike`, same as that function).
- `get_programme(programme_id)`
- `create_programme(name, code, program_type, description, uses_semesters, uses_terms, duration)`
- `update_programme(programme_id, **fields)`
- `set_programme_status(programme_id, status)` — activate/archive, mirrors `set_course_status`.
- `get_programme_departments(programme_id)` — returns list of linked `Department` objects.
- `set_programme_departments(programme_id, department_ids)` — replace-all: delete `ProgrammeDepartment` rows for this programme not in `department_ids`, insert missing ones. Mirrors `set_prerequisites`/`set_corequisites` in `services/admin_course.py`.

`list_active_programmes()` (already in `services/admin_student.py`) is reused as-is, not duplicated.

## RBAC

New permission `programmes.manage`, seeded in `seed_dev_data.py` alongside the existing permission list, granted to both **Super Administrator** and **Academic Administrator** roles — the same pair that holds `departments.manage`.

## Admin routes (`app.py`)

Mirrors the existing `/admin/departments` route family exactly:

- `GET /admin/programmes` — list + search/status filter
- `GET, POST /admin/programmes/new` — create
- `GET /admin/programmes/<int:programme_id>` — detail (includes linked Departments + the assignment form)
- `GET, POST /admin/programmes/<int:programme_id>/edit` — edit
- `POST /admin/programmes/<int:programme_id>/departments` — calls `set_programme_departments`
- `POST /admin/programmes/<int:programme_id>/activate`
- `POST /admin/programmes/<int:programme_id>/archive`

All gated by `@permission_required('programmes.manage')`.

## Templates

New `templates/admin/programmes.html` (list) and `templates/admin/programme_form.html` (create/edit), following the exact structure/CSS classes of `templates/admin/departments.html` / `department_form.html`. Programme detail view adds a checkbox list of all active Departments for assignment (small counts — no search widget needed), submitting to the `/departments` route above.

## Navigation

New sidebar item in `templates/admin/base_admin.html`, placed between "Departments" and "Sessions":
```html
<li><a href="{{ url_for('admin_programmes') }}" class="{{ 'active' if request.endpoint and request.endpoint.startswith('admin_programme') }}"><i class="fas fa-graduation-cap"></i> Programmes</a></li>
```

## Testing

No automated test framework (established convention). Manual verification via a throwaway `test_client`/`app_context` script:
1. Migration applies cleanly; all 5 existing Programmes have `uses_semesters=True`, `uses_terms=False`, `duration=None`.
2. Backfill produces `ProgrammeDepartment` rows matching existing `(User.programme_id, User.department_id)` pairs in seeded dev data.
3. `create_programme` / `update_programme` / `set_programme_status` work via direct service calls.
4. `set_programme_departments` correctly replaces links (add one, remove one, verify final state).
5. `/admin/programmes` routes render and respect `programmes.manage` permission (Academic Administrator can access, a role without the permission cannot).
6. Regression: existing `/admin/departments` and `/admin/courses` pages still work unchanged.

## Deliverables

1. Migration: add `Programme.uses_semesters`/`uses_terms`/`duration`, create `programme_departments` table, backfill both.
2. `ProgrammeDepartment` model in `models.py`.
3. `services/admin_programme.py` with the six functions above.
4. `programmes.manage` permission, seeded and granted to Super Administrator + Academic Administrator.
5. Admin routes in `app.py`.
6. `templates/admin/programmes.html`, `templates/admin/programme_form.html`, Programme detail department-assignment UI.
7. Sidebar nav item.
8. Manual verification per the Testing section above.
