# Current Development State

## Active Worktree
worktree-admin-phase2-core-academic

## Current Milestone
Admin Portal Phase 2 – Core Academic Data

## Last Commit
a9d4867 feat: add bulk student status action (activate/suspend/deactivate) wired to the directory's bulk-select bar

## Completed
- Task 1: Data model — Department, Programme, CoursePrerequisite/Corequisite, CourseAssessmentComponent, AcademicHoliday, Student/Course import job+error tables; first real Alembic migration + backfill
- Task 2: Shared validation/CSV-import services, `departments.manage` permission
- Task 3: Departments module CRUD
- Task 4: Academic Sessions CRUD + clone
- Task 5: Registration Periods/Semesters, single-active enforcement, holidays
- Task 6: Course Management core CRUD + directory
- Task 7: Course prerequisites/corequisites/assessment structure
- Task 8: Course CSV import
- Task 9: Student Management directory + profile page
- Task 10: Student account management + manual creation
- Task 11: Student CSV import + admission-portal interface stub
- Task 12: Bulk Student Status Action (activate/suspend/deactivate via directory's bulk-select bar)

## In Progress
- Task 13: Whole-milestone smoke test and DEVELOPMENT_PROGRESS.md update

## Next
- Task 13: run whole-milestone smoke test + schema check, update `DEVELOPMENT_PROGRESS.md` to record Phase 2 as complete, commit
- After Task 13: merge `worktree-admin-phase2-core-academic` into `main` (same flow as Admin Foundation's `013e49e`)
- Then: Admin Portal Phase 3 (Registration Oversight, Bulk Operations, Student Onboarding Management) — pending approval

## Blockers
- None

## Ready To Merge
- No (Task 13 not yet committed)

## Notes
- This worktree lives at `.claude/worktrees/admin-phase2-core-academic` on branch `worktree-admin-phase2-core-academic`, diverged from `main` at commit `c4b4232`. Do not switch this worktree to `main` or create a new worktree/branch for this milestone.
- Plan checkboxes in `docs/superpowers/plans/2026-08-02-admin-phase2-core-academic-data.md` are not edited as tasks complete in this repo's convention — completion is tracked via commit history instead. This file (`CURRENT_STATE.md`) is the authoritative up-to-date handoff; update it immediately after every commit in this worktree.
- No automated test framework in this repo — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed (per the plan's Global Constraints).
- `bulk_set_status` in `services/admin_student.py` is a direct N-repeat of the Task 10 single-student status actions — the only bulk action in Phase 2 scope; bulk email/export/course-registration are explicitly Phase 3.
- `main`'s root also has an untracked `migrations/` scaffold directory (`alembic.ini`, `env.py`, `README`, `script.py.mako`) left over from local Flask-Migrate setup — separate from this worktree's real migration, harmless, unresolved housekeeping item flagged for whoever merges this branch.
