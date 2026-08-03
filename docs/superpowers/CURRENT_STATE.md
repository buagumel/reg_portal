# Current Development State

## Active Worktree
None — `worktree-admin-phase3-academic-operations` was merged into `main`, the milestone is closed, and the worktree/branch have both been removed (the worktree directory is gone from `.claude/worktrees/`, the local branch was deleted with `git branch -d` after confirming its tip was an ancestor of `main`'s new HEAD).

## Current Milestone
None in progress. Last completed: Admin Portal Phase 3 — Academic Operations (merged).

## Last Commit
a576cfb Merge branch 'worktree-admin-phase3-academic-operations': Admin Portal Phase 3 (Academic Operations)

## Completed
- Admin Portal Phase 3 (Academic Operations) — all 16 plan tasks (Phase 3 data model/migration, course capacity enforcement + lock checks, `last_login_at`/`onboarding_completed_at`, level validation, CSV import preview + duplicate-email detection for students and courses, manual-creation onboarding email, bulk reset-password/resend-email/assign-department/assign-programme, CSV/Excel Export Center, configurable Add/Drop window, Registration Oversight dashboard, per-student Registration Management overrides, course enrollment/capacity display, Student Onboarding Management dashboard + analytics, per-student onboarding actions with a Super-Admin-only "mark complete", whole-milestone smoke test + docs) — see `DEVELOPMENT_PROGRESS.md` for full detail. Executed via `superpowers:subagent-driven-development` — a fresh implementer + independent reviewer per task, two fix rounds along the way (Task 8: stale-student_id partial-batch audit gap; Task 12: unguarded date-parse crash path), plus a final whole-branch review (opus) that caught 5 additional cross-task findings and triggered one more fix wave before merge.
- Merged into `main` via `a576cfb` (`--no-ff`, matching the Admin Foundation/Phase 2 merge pattern).
- Post-merge, `main`'s real dev database was brought current using the same now-familiar workaround: dropped the empty `registration_overrides` table `db.create_all()` had auto-created on import, temporarily neutralized the migration's `op.create_table(...)` block for one `flask db upgrade` run, reverted the migration file immediately after (`git checkout`), then ran `python seed_dev_data.py` (idempotent) to seed `onboarding.override` and sync Academic Administrator's newly-added `students.manage` permission onto the already-existing seeded role. Alembic is now stamped at head (`c95349c0e1ad`).
- Full post-merge smoke test re-run and passed on `main` (all 11 real Phase 1-3 admin routes 200, Announcements/Reports still correctly stub, all 10 export combinations downloaded, schema + column checks pass, student login/`last_login_at`/Add-Drop/Registration routes all still work).

## In Progress
- None

## Next
- Admin Portal Phase 4 (Finance & Payment Administration) — not yet started, pending approval/brainstorming with the user before a design spec is written.

## Blockers
- None

## Ready To Merge
- N/A — already merged into `main`.

## Notes
- **The `db.create_all()`-vs-Alembic hazard (flagged after Phase 2, confirmed again here) is now a fully established, recurring pattern for this repo**: every time a new migration is merged into `main` and applied to the real dev database, expect `db.create_all()` to have already auto-created any brand-new *tables* the new models introduce (harmless, idempotent) while never adding new *columns* to already-existing tables. The fix is always the same: confirm the auto-created table(s) are empty, drop them, temporarily comment out just the `op.create_table(...)` block(s) in the generated migration for one `flask db upgrade` run, revert the migration file via `git checkout` immediately after, then re-run `seed_dev_data.py`. This has now happened identically for both the Phase 2 and Phase 3 migrations.
- No automated test framework in this repo — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed. This convention was followed at every layer of the subagent-driven workflow too: implementers, task reviewers, and the final whole-branch reviewer all used manual scripts, never a committed test file.
- **A stray `.git/worktrees/<old-worktree-name>` metadata directory (e.g. `course-add-drop`) has been undeletable (Windows permission error) throughout this entire project's history** — it surfaces as a harmless warning on nearly every commit/worktree operation (`error: failed to delete '.git/worktrees/...': Permission denied`) but has never once blocked an actual commit or merge. Safe to ignore.
- `git worktree remove`/`ExitWorktree` can fail to physically delete a worktree directory on Windows even after git's own metadata considers it removed (as happened when finishing this branch) — `git worktree list` may already show it gone while the directory itself lingers on disk. If so, delete the leftover directory manually (safe once you've confirmed via `git merge-base --is-ancestor <branch> main` that its commits are already part of `main`'s history) and then `git branch -d` the branch normally.
- Two RBAC/permission changes only exist because `seed_dev_data.py` was re-run after this merge (Academic Administrator's new `students.manage` grant, the `onboarding.override` permission) — if a fresh clone or a different dev database is ever used, remember to run `python seed_dev_data.py` after `flask db upgrade`, not just the migration.
- One parked, non-blocking finding from the final whole-branch review: `get_effective_add_drop_deadline`'s `max(base_close, override)` logic means an *earlier* `deadline_override` (an admin shortening rather than extending a deadline) is silently a no-op once a period configures an explicit Add/Drop window, even though the same earlier override *does* shorten the main registration window via `get_window_status`. Matches the literal scope of "extend when later," not reachable through the normal Extend-Deadline UI framing, but worth knowing if `extend_deadline`'s validation is ever tightened.
