# DDD Refactor Sub-project 5: FeeStructure Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-09

## Context

This is sub-project 5 of 5 — the last sub-project — in the Programme-centered DDD academic architecture refactor (see `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` for the full audit and decomposition). Sub-projects 1-4 (Programme↔Department Foundation, Academic Calendar, Course/CourseOffering Split, Student & Registration Programme-awareness) are complete and merged. After this sub-project, Phase C (Student/Admin Portal end-to-end verification + `DEVELOPMENT_PROGRESS.md` update) closes out the refactor.

## Current state (confirmed by codebase audit)

There are two, entirely separate fee mechanisms in this codebase today:

1. **`DepartmentRegistrationRule`** (`registration_period_id` + `department` string → `min_credits`/`max_credits`/`registration_fee`) — already scoped per `RegistrationPeriod`, resolved via `services/registration.py::get_credit_limits(period, department)`, and charged automatically as the `registration_fee` `PaymentCategory` at `register_student()` time. Deliberately deferred to this sub-project by sub-project 4's design doc, but confirmed **untouched** by this sub-project (see Decisions below) — it keeps working exactly as it does today.
2. **`PaymentCategory`/`PaymentItem`** — a flat, global fee catalog (`registration_fee`, `library_fee`, `laboratory_fee`, `acceptance_fee`, `hostel_fee`, `transcript_fee`, `id_card`, `late_registration`), each with a single `default_amount` shown identically to every student via `/payment/create` (`app.py::payment_create_page`/`payment_create_submit`), with zero Programme/Session/Semester/Department awareness. This is the mechanism this sub-project makes Programme/session-aware.

Real data (confirmed live): 8 `PaymentCategory` rows; `registration_fee`'s `default_amount` is `None` (excluded from `/payment/create`'s list today via `if c.default_amount is not None`, since it's populated via `DepartmentRegistrationRule` instead), the other 7 have real default amounts. 11 users total: 10 have `department_id` set, 6 have `programme_id` set (same incomplete-backfill state confirmed in sub-project 4). 4 `AcademicSession` rows: sessions 1-3 unscoped (`programme_id=None`), session 4 scoped to Programme 3; session 2 (`2026/2027`, unscoped) is the only currently-`is_current` session on real data.

`PaymentCategory`/`PaymentItem`/`Payment`/gateway integration (Phase 9-11) are frozen — no schema or behavior changes to any of them. `PaymentCategory` itself has no admin UI today (managed only via `seed_dev_data.py`).

## Decisions made before design (user-confirmed)

1. **Scope: the general payment catalog only.** `FeeStructure` makes `PaymentCategory` amounts (shown on `/payment/create`) vary by Programme/Session/Semester/Department, as a new additive lookup layer that falls back to `PaymentCategory.default_amount` when no scoped row matches. `DepartmentRegistrationRule`/`registration_fee`/`register_student()`'s fee resolution are **not touched** — a separate, already-working, narrower mechanism.
2. **Fee Category = `PaymentCategory` via FK.** No new category concept — `FeeStructure.category_id` references the existing `PaymentCategory` table admins/seed data already populate.
3. **Semester is optional on `FeeStructure`** — `NULL` means "applies to every semester in that session" (e.g. an annual hostel fee that doesn't repeat per semester). An exact-semester row, when present, takes priority over a session-wide (`NULL`) row for the same session/department/category.
4. **Session resolution uses a new `get_current_session(user)` helper**, independent of whether a registration period happens to be open — general fee payment (tuition, hostel, ID card, etc.) isn't conceptually gated on registration being open, unlike `get_active_period(user)`.
5. **Includes a minimal admin CRUD UI** for `FeeStructure` rows (list/create/edit/delete), consistent with every other DDD sub-project that added configurable state (Programme management, Session/Period UI, Course Catalog all got admin UIs).

## Data model changes

### New model: `FeeStructure`

```python
class FeeStructure(db.Model):
    __tablename__ = 'fee_structures'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('payment_categories.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')
    department = db.relationship('Department')
    category = db.relationship('PaymentCategory')

    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None
```

Programme-awareness comes transitively through `academic_session_id`, mirroring `RegistrationPeriod.programme`/`CourseOffering.programme` from sub-projects 2 and 4 — no separate `programme_id` column. `semester_id` and `department_id` are both nullable; `NULL` on either means "applies to every value of that axis within this session." No `is_active` flag (YAGNI — admins edit/delete rows directly; nothing else about this model needs soft-disable). Migration: new table only, no changes to any existing table.

**Uniqueness:** no DB-level `UNIQUE` constraint, since SQLite treats each `NULL` in a composite unique index as distinct (the same reasoning sub-project 2's `is_session_name_unique` was built around) — a `(academic_session_id, semester_id, department_id, category_id)` DB constraint would not actually prevent duplicate `NULL`-vs-`NULL` rows. Instead, a service-layer `is_fee_structure_scope_unique(...)` check runs before insert/update, exactly mirroring `is_session_name_unique`'s pattern.

## Service layer: `services/fee_structure.py` (new file)

```python
def get_current_session(user=None):
    """AcademicSession-level analog of get_active_period(): returns the
    is_current=True session in user's Programme's scope group, falling back
    to the shared/legacy is_current session if the user has no programme_id
    or their Programme has no current session of its own. user=None (or a
    user whose scope group and the legacy group both lack a current
    session) returns the shared/legacy current session only, or None if
    even that doesn't exist."""
    if user is not None and user.programme_id is not None:
        programme_session = AcademicSession.query.filter(
            AcademicSession.is_current == True,
            AcademicSession.programme_id == user.programme_id,
        ).order_by(AcademicSession.id.desc()).first()
        if programme_session is not None:
            return programme_session

    return AcademicSession.query.filter(
        AcademicSession.is_current == True,
        AcademicSession.programme_id.is_(None),
    ).order_by(AcademicSession.id.desc()).first()


def resolve_fee_context(user):
    """Returns (session, semester_id). session is always
    get_current_session(user) — independent of whether a registration
    period is currently open. semester_id comes from get_active_period(user)
    only when that period's academic_session_id matches the resolved
    session (so a period active in a DIFFERENT scope group's session never
    leaks its semester into this one); otherwise None (session-wide)."""
    session = get_current_session(user)
    semester_id = None
    if session is not None:
        period = get_active_period(user)
        if period is not None and period.academic_session_id == session.id:
            semester_id = period.semester_id
    return session, semester_id


def resolve_amount(user, category):
    """Returns the Decimal amount to charge `user` for `category`: the most
    specific matching FeeStructure row, tried in order
    (session, semester, dept) -> (session, semester, NULL) ->
    (session, NULL, dept) -> (session, NULL, NULL), falling back to
    category.default_amount when no row matches (or the user has no
    resolvable current session at all). A user with no department_id can
    only match NULL-department rows — never silently charged a
    department-specific amount without a resolved department."""
    session, semester_id = resolve_fee_context(user)
    if session is not None:
        department_id = user.department_id
        candidates = [(semester_id, department_id), (semester_id, None)]
        if department_id is not None:
            candidates.append((None, department_id))
        candidates.append((None, None))
        seen = set()
        for sem, dept in candidates:
            key = (sem, dept)
            if key in seen:
                continue
            seen.add(key)
            row = FeeStructure.query.filter_by(
                academic_session_id=session.id, semester_id=sem,
                department_id=dept, category_id=category.id,
            ).first()
            if row is not None:
                return row.amount
    return category.default_amount


def get_payable_categories(user):
    """Returns [(category, amount), ...] for every active PaymentCategory
    with a resolvable, non-None amount for this user — powers
    /payment/create. A category with neither a default_amount nor a
    matching FeeStructure row (e.g. registration_fee, handled by
    DepartmentRegistrationRule instead) is excluded, exactly matching
    today's `if category.default_amount is not None` filter."""
    result = []
    for category in PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all():
        amount = resolve_amount(user, category)
        if amount is not None:
            result.append((category, amount))
    return result
```

Note the `candidates` list construction: when `semester_id is None` (no active period matching the resolved session), `(semester_id, department_id)` and `(None, department_id)` would be the same tuple — the `seen` set guards against querying that combination twice, not against any correctness issue.

## Consumer wiring

- `app.py::payment_create_page` (GET): replaces `[c for c in get_active_categories() if c.default_amount is not None]` with `get_payable_categories(current_user)`.
- `app.py::payment_create_submit` (POST): replaces the `category.default_amount` lookup (line 717) with `resolve_amount(current_user, category)`, so the server-side amount used to actually create the `Payment`/`PaymentItem` matches what the student was shown — never trusts a client-submitted amount (already true today, unchanged).
- `templates/payment_create.html`: iterates `(category, amount)` pairs instead of reading `category.default_amount` directly; `data-amount` JS attribute updated to use the resolved amount.
- `services/payment.py::get_active_categories()` has exactly one call site today (`app.py:686`, the one being replaced — confirmed via grep) and becomes dead code once `get_payable_categories` replaces it; deleted as part of this sub-project rather than left behind unused.
- `DepartmentRegistrationRule`, `get_credit_limits`, `register_student()` — **zero changes**.

## Admin CRUD UI

New `services/admin_fee_structure.py`: `list_fee_structures(programme_id=None)`, `create_fee_structure(...)`, `update_fee_structure(id, ...)`, `delete_fee_structure(id)`, `is_fee_structure_scope_unique(session_id, semester_id, department_id, category_id, exclude_id=None)`.

New admin routes + a `Fee Structure` admin page (list grouped by session, add/edit form: Session dropdown → Semester dropdown with an explicit "All semesters" option → Department dropdown with an explicit "All departments" option → Category dropdown → Amount). Follows the existing Sessions/Periods (sub-project 2) and Course Catalog (sub-project 3) admin-page conventions: same table/form layout, same RBAC permission-gating pattern (reuses whichever permission already gates Sessions management, e.g. `sessions.manage`, rather than inventing a new one — confirmed at plan time).

## Explicitly out of scope

- `DepartmentRegistrationRule`/`registration_fee`/`register_student()`'s fee resolution.
- Any schema or behavior change to `PaymentCategory`, `PaymentItem`, `Payment`, `PaymentReceipt`, `GatewayResponse`, or the payment gateway integration itself.
- A new category concept — `FeeStructure` references `PaymentCategory` directly.
- Admin UI for `PaymentCategory` itself (still seed-managed) — only `FeeStructure` gets a UI.

## Testing

No automated test framework (established convention) — manual verification via throwaway `test_client`/`app_context` scripts:
1. `get_current_session(user)` for a student whose Programme has its own `is_current` session returns that session; for a student with no Programme (or whose Programme has no current session) falls back to the shared/legacy current session; `get_current_session(None)` matches the shared/legacy-only behavior.
2. `resolve_amount`: a category with a session+semester+department-specific `FeeStructure` row resolves to that row's amount for a matching student, and to a *different* value (or the default) for a student in a different department/semester. A category with only a session-wide (`NULL`/`NULL`) row resolves to that row's amount for every student in that session regardless of department. A category with no `FeeStructure` row at all resolves to `category.default_amount`. A student with no `department_id` never receives a department-specific row's amount.
3. `get_payable_categories`: `registration_fee` (no `default_amount`, no `FeeStructure` row in current data) stays excluded from `/payment/create`'s list, exactly as today.
4. Full HTTP-level regression: `/payment/create` GET renders the same 7 categories/amounts as before this sub-project for a student with no scoped `FeeStructure` overrides (pure fallback path); POST still creates a correct `Payment`/`PaymentItem` for a scoped student once a `FeeStructure` override exists, and the created `PaymentItem.amount` matches the override, not the stale default.
5. Admin CRUD: create/edit/delete a `FeeStructure` row through the new admin UI; `is_fee_structure_scope_unique` rejects a duplicate `(session, semester, department, category)` scope, including the `NULL`/`NULL` cases.
6. Regression: registration flow (`register_student`, `get_credit_limits`, `DepartmentRegistrationRule`) unaffected — confirm a real registration + its `registration_fee` `Payment` still behaves identically to before this sub-project.

## Deliverables

1. `FeeStructure` model + migration (new table only).
2. `services/fee_structure.py`: `get_current_session`, `resolve_fee_context`, `resolve_amount`, `get_payable_categories`.
3. `app.py::payment_create_page`/`payment_create_submit` rewired to use resolved amounts; `templates/payment_create.html` updated.
4. `services/admin_fee_structure.py` + admin routes + `Fee Structure` admin page (list/create/edit/delete).
5. Manual verification per the Testing section above.
