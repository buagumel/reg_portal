# Current Development State

## Active Worktree
None — `worktree-dashboard-ongoing-registration-card` was merged into `main`, the feature is closed, and the worktree/branch have both been removed (leftover directory manually deleted after `ExitWorktree` hit the same Windows file-lock it always does — see Notes; local branch deleted with `git branch -d` after confirming its tip was an ancestor of `main`'s new HEAD).

## Current Milestone
None in progress. Last completed: Dashboard Ongoing Registration Card (small feature, merged). Before that: Admin Portal Phase 3 — Academic Operations (merged).

## Last Commit
e9610cc Merge branch 'worktree-dashboard-ongoing-registration-card': Dashboard Ongoing Registration Card

## Completed
- **Dashboard Ongoing Registration Card** (student-facing, small/self-contained) — a new card on the dashboard, shown above "Registered Courses (Current)" whenever a student has a registration for the active period that hasn't reached course-submission (payment-pending or paid-not-submitted), plus a matching "Complete Registration" CTA and submitted-confirmation state added to the existing `/registration` page (which previously had no next-step action at all once payment succeeded). Purely additive — no schema changes, one new key (`add_drop_window_status`) added to `services/registration.py`'s `get_registration_status_context` return dict. 2 plan tasks + 1 final-review fix wave, all via `superpowers:subagent-driven-development`.
  - **Real bug caught by the final whole-branch review** (not either task-level review): the new "Complete Registration" button was the *only* link to `/add_drop` anywhere in the UI (confirmed via grep) and rendered unconditionally once paid — it didn't check whether the Add/Drop window was open or whether the registration was admin-locked (`StudentRegistration.is_locked`). A student could click through to a page where every action silently failed with a toast. Fixed: both CTAs now gate on the real `get_add_drop_window_status(period, existing_registration)` (not just the coarser main registration window) and `not is_locked`, with explanatory fallback text ("Course selection is closed." / "Locked by administrator — contact the registry.") when suppressed.
  - Spec: `docs/superpowers/specs/2026-08-04-dashboard-ongoing-registration-card-design.md`. Plan: `docs/superpowers/plans/2026-08-04-dashboard-ongoing-registration-card.md`.
- Admin Portal Phase 3 (Academic Operations) — all 16 plan tasks — see `DEVELOPMENT_PROGRESS.md` for full detail. Merged via `a576cfb`.

## In Progress
- None

## Next
- Admin Portal Phase 4 (Finance & Payment Administration) — not yet started, pending approval/brainstorming with the user before a design spec is written.

## Blockers
- None

## Ready To Merge
- N/A — already merged into `main`.

## Notes
- **The `db.create_all()`-vs-Alembic hazard remains the standing hazard for any future migration** (unchanged from before — this feature added no schema, so it wasn't triggered this time). When it next comes up: confirm the auto-created table(s) are empty, drop them, temporarily comment out just the `op.create_table(...)` block(s) for one `flask db upgrade` run, revert the migration file via `git checkout` immediately after, then re-run `seed_dev_data.py`.
- **`main`'s real dev database (`instance/database.db`) is genuinely fragile in this environment.** Partway through this session it was found reverted to a near-pristine 1-user state with `migrations/` entirely missing from the working tree — most likely a OneDrive sync interaction with this project living under `OneDrive\Documents\reg_portal`, not a git issue (git history was untouched throughout; `git checkout -- migrations/` fully restored the tracked files). It was rebuilt via `flask db stamp head` (schema already matched current `models.py` via `db.create_all()`) + `seed_dev_data.py` + the standard department backfill script. **If `main`'s dev DB ever looks emptier than expected again, suspect this same cause first** — check `git status` for unexpected working-tree deletions before assuming data was legitimately lost.
- Verifying a fix on `main`'s actual dev database can differ from the isolated worktree's fresh seed in surprising ways: this session's post-merge verification initially failed because `main`'s active `RegistrationPeriod` already had a real, explicitly-configured Add/Drop window (`add_drop_opens_at`/`add_drop_closes_at` both set, left over from earlier Phase 3 verification work) — meaning `get_add_drop_window_status` correctly ignored the main window's `closes_at` and used the configured add/drop window instead, exactly as designed. Not a bug; the ad hoc verification script just needed to mutate the *right* fields for that period's actual configuration. Always inspect the specific period's fields before writing a "close the window" test against `main`.
- No automated test framework in this repo — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed.
- **A stray `.git/worktrees/<old-worktree-name>` metadata directory has been undeletable (Windows permission error) throughout this entire project's history** — now includes `admin-phase3-academic-operations`, `course-add-drop`, and `dashboard-ongoing-registration-card`. Surfaces as a harmless warning on nearly every commit/worktree operation but has never once blocked an actual commit or merge. Safe to ignore.
- `EnterWorktree` has consistently branched from a stale `origin/main` instead of local `main`'s actual tip, every single time it's been used this project — always verify with `git log --oneline -3` immediately after creating a new worktree, and `git reset --hard <local-main-tip-sha>` if it's wrong (safe on a just-created, zero-commits-yet worktree).
- `ExitWorktree`'s `action: "remove"` has consistently failed to physically delete the worktree directory on Windows (same file-lock family as the `.git/worktrees/` issue above) even after confirming `discard_changes: true` and after git's own metadata considers it removed. Recovery each time: `git worktree prune`, then manually delete the leftover directory (safe once confirmed via `git merge-base --is-ancestor <branch> main`), then `git branch -d` normally.
- Any admin action's audit-log/state fields left mutated by a throwaway verification script that crashes mid-script (before its own cleanup runs) can silently persist — this happened again this session (a failed test attempt left seed student `2308-2301-0002`'s `onboarding_completed`/`email_verified` at `True`/`True` instead of the seeded `False`/`False`; caught and restored). When a verification script errors out, always re-check and manually restore any fields it was supposed to clean up, don't assume a later successful re-run's own "restore to original" logic will recover the *true* original if it captured its "original" value after an earlier failed run already mutated it.
