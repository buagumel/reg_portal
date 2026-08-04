# DDD Refactor Sub-project 3: Course → Course + CourseOffering Split Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-04

## Context

This is sub-project 3 of 5 in the Programme-centered DDD academic architecture refactor (see `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` for the full audit and decomposition). Sub-projects 1-2 (merged) related `Programme`↔`Department` and scoped `AcademicSession`/`RegistrationPeriod` to `Programme`. This sub-project splits the conflated `Course` model (today: one row per session/semester offering, re-entering code/title/credits every time) into a master `Course` (catalog identity) and `CourseOffering` (one session/semester's instance of it).

## Current state (confirmed by codebase audit)

`Course` (`models.py:189-211`) has a unique constraint on `(code, academic_session_id, semester_id)` — the same course code gets a brand-new row, with re-entered `title`/`credits`/`description`, every time it's offered. Real data on `main` already demonstrates the problem: "CSC 212 / Digital Logic / 3 credits" exists as two separate rows today, offered under Computer Science in one session and Information Technology in another — same course, two independently-typed-in offerings.

`RegisteredCourse.course_id` (`models.py:214-225`), `CoursePrerequisite`/`CourseCorequisite`/`CourseAssessmentComponent` (`models.py:393-424`) all FK into `courses.id`. `services/admin_course.py` and `services/course_import.py` (CSV import) both read/write the conflated model directly. `services/validation.py::validate_course_eligible` and `services/registration.py::add_course`/`get_course_enrollment_count` are the live, student-facing paths that key off `course_id`.

## Migration strategy: rename, don't rebuild

Rather than building a new `CourseOffering` table and migrating data into it (re-keying every row, repointing every FK), the existing `courses` table is renamed in place to `course_offerings` via `op.rename_table` — same rows, same IDs, same columns, nothing moved or dropped. SQLite automatically updates every sibling table's stored FK text to match the new name. This is safe specifically because it's a single, permanent rename with nothing ever dropped — sub-project 2's Task 1 fix round established that the *unsafe* case is renaming a table away to an intermediate name and then dropping it, not renaming it once and leaving it renamed.

- `courses` → renamed to `course_offerings`. Every existing column stays: `code`, `title`, `credits`, `course_type`, `description`, `department`/`department_id`, `level`, `academic_session_id`, `semester_id`, `instructor`, `schedule`, `max_capacity`, `status`.
- **`RegisteredCourse.course_id` needs zero code changes** — it already points at these exact rows; only the underlying table name changes.
- New master `Course` table: `id`, `code` (unique), `title`, `credits`, `course_type`, `description`, `status` (default `'active'`), `created_at`.
- New `course_offerings.course_id` (nullable FK → the new `courses.id`) — nullable at the DB level for migration safety, but every new offering created through the service layer going forward always sets it.
- Migration backfill: group existing `course_offerings` by `code`, create one master `Course` row per distinct code (using the first-encountered `title`/`credits`/`course_type`/`description` as authoritative; any code where these differ across existing rows — like the CSC 212 case, if it turns out to differ in course_type/description too — gets flagged in the migration's own output for admin awareness, not silently resolved), and set every offering's new `course_id` accordingly.

### Prerequisites/Corequisites move to master (per user decision)

`CoursePrerequisite`/`CourseCorequisite` currently FK into the conflated table (today effectively per-offering, though nothing exercises that granularity). Per the confirmed design decision, these become curriculum-level: their `course_id`/`prerequisite_course_id`/`corequisite_course_id` columns get repointed from offering-rows to the new master `Course` rows, translated via the same code→master-id mapping built during the backfill above. This requires rebuilding both tables' FK constraints (`batch_alter_table`) to target the new master `courses` table, plus a data `UPDATE` translating existing values. `CourseAssessmentComponent` is explicitly NOT moved — it stays FK'd to `course_offerings.id`, unchanged, since assessment weighting is plausibly instructor/term-specific and this wasn't part of the confirmed decision.

## Admin UI changes

- New **Course Catalog** admin module: CRUD for master `Course` (create/edit/archive — code/title/credits/course_type/description), mirroring the Departments/Programmes module pattern established in sub-projects 1-2.
- The existing "New/Edit Course Offering" flow (today's `/admin/courses/new`) changes from free-text code/title/credits entry to picking an existing master `Course` (or creating one inline via the Course Catalog module) plus the offering-specific fields (department, level, session, semester, instructor, schedule, capacity, status). The existing `/admin/courses` list stays the CourseOffering list — no change to its role, just what creates a row.
- Prerequisite/corequisite management (currently on the course detail page, `set_prerequisites`/`set_corequisites`) moves to the master Course's admin page, since it's no longer offering-specific.

## CSV import (`services/course_import.py`)

- **New code:** create both the master `Course` (from the row's `code`/`title`/`credits`/`course_type`/`description`) and the `CourseOffering`, matching today's "created" path.
- **Existing code:** reuse the existing master `Course` as-is — a CSV upload never overwrites master catalog fields. If the row's `title`/`credits`/`course_type`/`description` differ from the existing master, that's flagged as a non-blocking warning in the import report (reusing the existing flagged-rows mechanism the import already has for duplicates/errors — extended with a new "mismatched master" category, not a new mechanism) — the row still imports, creating/updating only the `CourseOffering`. The master stays editable only through the Course Catalog module.
- Report shape (`created`/`updated`/`skipped`/`duplicate`/`error` counts) is otherwise unchanged.

## Student-facing scope (mechanical rename only, per user decision)

Every place that reads `Course.query`/`course.xxx` for student-facing purposes (`services/registration.py::add_course`/`drop_course`/`get_course_enrollment_count`, `services/validation.py::validate_course_eligible`, course-listing templates) is repointed to `CourseOffering.query`/`offering.xxx` — same field names (`department`, `level`, `code`, `title`, `credits`, etc.), same values, same behavior. `validate_course_eligible`'s legacy string-matching logic is untouched in substance, only renamed. No FK-based Programme-aware eligibility rewrite happens here — that is explicitly sub-project 4's job, per the original decomposition.

## Explicitly out of scope

- `Programme` linkage on `CourseOffering` (a `programme_id`/derivation from the session's Programme) — sub-project 4's job, consistent with how sub-project 2 deferred `RegistrationPeriod`'s Programme-awareness cutover.
- Any change to `CourseAssessmentComponent`'s scope (stays offering-level).
- `FeeStructure` — sub-project 5.

## Testing

No automated test framework (established convention) — manual verification via throwaway `test_client`/`app_context` scripts:
1. Migration: confirm `course_offerings` has every pre-existing course row intact (same IDs, same field values), confirm `PRAGMA foreign_key_check` is clean on `registered_courses`, `course_prerequisites`, `course_corequisites`, `course_assessment_components` after the rename+repoint.
2. Confirm the CSC 212 real-data case (or an equivalent constructed one) produces exactly one master `Course` row and the expected number of `CourseOffering` rows, each with the correct `course_id`.
3. Confirm `CoursePrerequisite`/`CourseCorequisite` rows correctly reference master `Course` ids post-migration (not offering ids).
4. Confirm student-facing registration (`add_course`, `drop_course`, eligibility checks, the dashboard/registration/add-drop pages) behaves identically before and after — same courses visible, same eligibility results, same enrollment counts.
5. Confirm the new Course Catalog admin module and updated New Offering flow work end-to-end, including creating a new offering against an existing master Course and confirming no duplicate master gets created.
6. Confirm CSV import: a new-code row creates both master+offering; an existing-code row with a mismatched title flags a warning but still creates the offering without mutating the master.
7. Regression: Departments, Programmes, Sessions admin pages and the full student portal (dashboard, registration, add/drop) unaffected.

## Deliverables

1. Migration: rename `courses`→`course_offerings`, new master `Course` table, `course_offerings.course_id`, backfill, `CoursePrerequisite`/`CourseCorequisite` repoint to master.
2. `models.py`: new `Course` (master) class, renamed `CourseOffering` class (was `Course`), updated relationships on `RegisteredCourse`/`CoursePrerequisite`/`CourseCorequisite`/`CourseAssessmentComponent`.
3. Service layer: new `services/admin_course_catalog.py` for master Course CRUD; `services/admin_course.py` updated for offering CRUD against a chosen master; `services/course_import.py` updated per the CSV behavior above; `services/registration.py`/`services/validation.py` repointed to `CourseOffering`.
4. Admin UI: new Course Catalog module (list/create/edit/archive), updated New/Edit Offering flow (master picker instead of free-text catalog fields), prerequisite/corequisite management moved to the master Course's page.
5. Manual verification per the Testing section above.
