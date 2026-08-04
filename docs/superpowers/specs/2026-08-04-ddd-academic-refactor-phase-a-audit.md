# DDD Academic Architecture Refactor — Phase A: Audit & Migration Strategy

**Status:** Approved
**Author:** Controller (Claude), approved by user 2026-08-04

## Problem

The current data model treats `Department` as if it were the top academic entity, and treats `Programme` (added in Phase 2) as disconnected metadata. In reality: the institution offers **Programmes** (ND, HND, Pre-HND, International Diploma, Advanced Diploma, CIFS/Foundation); students belong to a Programme; Departments (Computer Science, Accountancy, Business Administration, Mass Communication, ...) are shared across multiple Programmes, not owned by any one of them. Target hierarchy: **Institution → Programme → Department → Course Offerings → Student**, with Academic Calendar, Registration Rules, and Fee Structure all scoped per Programme.

This is an architectural evolution, not a rewrite: preserve all existing functionality and data, extend rather than replace, keep every existing student- and admin-facing workflow working throughout.

## Current architecture audit

Confirmed by direct inspection of `models.py` and `services/*.py` on `main` (commit `e9610cc`).

### Models

| Model | Programme-aware today? | Notes |
|---|---|---|
| `Programme` (Phase 2) | — | `id, name, code, program_type, description, status, created_at`. No relationship to `Department`. Structured metadata only, per its own Phase 2 design doc. |
| `Department` (Phase 2) | No | `id, name, code, faculty, head_name, status, created_at`. Independent of Programme. |
| `User` | Partially | Has **both** `department_id` (FK) and `programme_id` (FK) as two independent, unrelated FKs — nothing enforces the pair is a valid combination. Also carries legacy free-text `department`, `course`, `level`, `semester`, `session` columns, still the only columns every pre-Phase-2 student-facing read path uses. |
| `Course` | No | Has `department_id` but no `programme_id`. Unique constraint on `(code, academic_session_id, semester_id)` means the same course code gets a brand-new row every semester — no stable "master course" identity to hang prerequisites/history on. |
| `AcademicSession` | No | Flat, global: `id, name (unique), is_current, start_date, end_date, status`. |
| `Semester` | No | Flat, global lookup: `id, name (unique), order`. Shared by every programme regardless of semester-vs-term structure. |
| `RegistrationPeriod` | No | (session × semester) join, global. Not scoped to Programme. |
| `DepartmentRegistrationRule` | String-keyed | Keyed on the legacy `department` string, not `department_id` or any Programme. |
| `StudentRegistration` | No | Keyed on `user_id` + `registration_period_id` only. |
| `PaymentCategory` / `PaymentItem` | No | Flat fee catalog, not session- or Programme-scoped. |

### Services / logic

- `services/validation.py::validate_course_eligible` — matches `course.department != user.department` using the **legacy string columns**, not the `department_id` FKs that already exist and are already dual-written.
- `services/registration.py::get_credit_limits(period, department)` — also string-keyed, via `DepartmentRegistrationRule.department`.
- `services/admin_validation.py` — already has `resolve_department`, `resolve_programme`, `valid_levels_for_programme`, `LEVELS_BY_PROGRAM_TYPE`. Validation-only; Phase 3's final review explicitly deferred building a real schema-backed term/eligibility engine as future phase-sized work. This refactor is that deferred work.
- `services/admin_session.py`, `services/admin_course.py` — CRUD for `AcademicSession`/`RegistrationPeriod`/`Course`, no Programme parameter anywhere.
- `services/admin_student.py` — already has `bulk_assign_department`/`bulk_assign_programme` as two independent dual-write operations; a useful precedent for the "additive, dual-write" pattern this refactor continues.
- All routes live in `app.py` (2480 lines, no blueprints) — every affected route is identified per sub-project below as each is designed.

### Conclusion

The FK scaffolding for Programme-awareness partially exists (`User.programme_id`, `User.department_id`, `Course.department_id`) but nothing downstream reads it — every actual business rule (eligibility, credit limits, fee rules) still runs on legacy strings. Programme and Department are unrelated. There is no course/offering split, no term-cycle schema, no fee-per-programme schema.

## Migration principles (carried from Phases 2-3)

1. **Additive, not destructive.** New FK columns/tables alongside legacy ones. No column drops, no renames of columns still read by live code.
2. **Dual-write during transition.** New admin-driven writes populate both new and legacy fields, mirroring `admin_student.py`'s existing `department_id`+`department` pattern.
3. **Legacy read paths keep working unchanged** until a sub-project explicitly repoints them, verified by manual smoke test each time (established convention — no automated test suite in this repo).
4. **One sub-project = one brainstorm → spec → plan → subagent-implementation → merge cycle**, each gated by your approval, mirroring how Phase 2, Phase 3, and the dashboard-card feature were each done.

## Decomposition into sub-projects

Phase B of your original request (9 items) decomposes into 5 sequential sub-projects — each is a hard dependency for the next:

1. **Programme↔Department foundation.** Extend `Programme` (`uses_semesters`, `uses_terms`, `duration`), add `ProgrammeDepartment` junction (many-to-many). Admin Programme Management UI: create/edit/archive/activate Programme, assign Departments. No other model touched yet — this is the safe first slice everything else hangs off.
2. **Academic Calendar.** Scope `AcademicSession`/`RegistrationPeriod` to Programme; support semester-based and term-based cycles without hardcoding. **Open assumption carried forward:** your spec's own example (HND's "2026/2027" vs International Diploma's "2026/2027") shows the same calendar-year label under different Programmes with different sub-structures — meaning `AcademicSession` needs its own row per Programme even when the label matches, not one shared row. Proceeding on that basis unless redirected when this sub-project's design is presented.
3. **Course → Course + CourseOffering split.** Master `Course` (code/title/credits, stable identity) separate from `CourseOffering` (Programme, Department, Session, Semester/Term, Level, Capacity, Prerequisites, Corequisites, Status).
4. **Student & Registration Programme-awareness.** Make eligibility/credit-limit logic actually read `department_id`/`programme_id` FKs instead of legacy strings; `RegistrationPeriod` registration rules become Programme-scoped.
5. **FeeStructure.** New model: Programme, Academic Session, Semester/Term, Department (optional), Fee Category, Amount. Interacts with but does not replace the existing (frozen, Phase 9-11) `PaymentCategory`/`PaymentItem` — scoped as an additive layer, reconciled explicitly when this sub-project is designed.

Then **Phase C**: verify Student Portal, verify Admin Portal, update `DEVELOPMENT_PROGRESS.md` (architecture changes, migration notes, breaking changes, remaining tasks).

## Next step

Proceed into brainstorming sub-project 1 (Programme↔Department foundation) as its own design cycle.
