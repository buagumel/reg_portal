# Current Development State

## Active Worktree
None — `worktree-admin-phase2-core-academic` was merged into `main` and the milestone is closed. The worktree directory (`.claude/worktrees/admin-phase2-core-academic`) and its branch still exist on disk (host/harness-managed, not removed) but there is no active work on them.

## Current Milestone
None in progress. Last completed: Admin Portal Phase 2 – Core Academic Data (merged).

## Last Commit
788dddb Merge branch 'worktree-admin-phase2-core-academic': Admin Portal Phase 2 (Core Academic Data)

## Completed
- Admin Portal Phase 2 (Core Academic Data) — all 13 plan tasks (Data model/migration, shared services, Departments, Academic Sessions, Registration Periods/holidays, Course Management, prerequisites/corequisites/assessment, Course CSV import, Student Management directory/profile, student account management/manual creation, Student CSV import/admission-portal stub, Bulk Student Status Action, whole-milestone smoke test + docs) — see `DEVELOPMENT_PROGRESS.md` for full detail.
- Merged into `main` via `788dddb` (`--no-ff`, matching the Admin Foundation merge pattern `013e49e`).
- Post-merge, `main`'s real dev database (`instance/database.db`) was brought current: dropped 10 empty Phase-2 tables that `app.py`'s unconditional `db.create_all()` had auto-created on import (harmless but blocked Alembic's `create_table`), then ran `flask db upgrade` (with the migration's `op.create_table` calls temporarily neutralized for that one run, reverted immediately after via `git checkout` — committed migration file is unchanged) to add the new columns to `users`/`courses`/`registration_periods`/`academic_sessions` and run the Department backfill (created 2 Department rows, backfilled department_id on 5/6 users and 10/10 courses on this dev DB). Then ran `python seed_dev_data.py` (idempotent) to seed the new `departments.manage` permission onto both admin roles and the 5 `Programme` reference rows — required for `/admin/departments` etc. to be reachable. Alembic is now correctly stamped at head (`42e5946fa0ab`).
- Full post-merge smoke test re-run and passed on `main` after the above fixes (all 6 real Phase 2 routes 200, Announcements/Reports still correctly stub, schema + column checks pass).

## In Progress
- None

## Next
- Admin Portal Phase 3 (Registration Oversight, Bulk Operations, Student Onboarding Management) — not yet started, pending approval/brainstorming with the user before a design spec is written.
- Housekeeping (not blocking): decide whether to `git worktree remove` and delete the now-merged `worktree-admin-phase2-core-academic` worktree/branch, or leave them — left in place for now since this session's worktree access was host/harness-managed (`.claude/worktrees/...`), not created via the Superpowers worktree convention, so cleanup wasn't performed automatically.

## Blockers
- None

## Ready To Merge
- N/A — already merged into `main`.

## Notes
- **Known hazard for the next migration:** `app.py` line ~90 runs `db.create_all()` unconditionally at import time, every time `app` is imported (including via `flask db upgrade`, which loads `app.py` as `FLASK_APP` before Alembic runs). `create_all()` is idempotent for whole missing tables (silently no-ops if they already exist) but cannot add columns to existing tables — that's what real migrations are for. The net effect: **any new model class you add to `models.py` will get silently auto-created as an empty table the moment `app` is imported**, which will make a subsequent `flask db migrate`/`flask db upgrade` for that same table fail with "table already exists" unless you either (a) run `flask db upgrade` against a database that has never imported the new model yet, or (b) temporarily strip the `op.create_table(...)` call(s) for tables that already exist before running `upgrade`, then revert. This bit both the worktree's dev DB (presumably handled the same way) and `main`'s dev DB during this merge.
- No automated test framework in this repo — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed.
- `main`'s previously-untracked `migrations/` scaffold directory is now resolved — those files are tracked as of the merge (they came in identical to what was already there).
- Two admin permission/role rows and a handful of reference rows only exist because `seed_dev_data.py` was re-run after the merge — if a fresh clone or a different dev database is ever used, remember to run `python seed_dev_data.py` after `flask db upgrade`, not just the migration.
