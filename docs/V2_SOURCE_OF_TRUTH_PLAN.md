# V2 Source Of Truth Plan

## Purpose
This document defines the database source-of-truth model for IFMS Salary Report Analyzer and a minimal route-conversion plan so future changes do not mix V1 and V2 unintentionally.

## Authoritative Tables (Going Forward)
The following tables are the canonical data model for active app behavior:

- `bills_v2`
- `employees_v2`
- `employee_components_v2`
- `validation_issues_v2`
- `dictionary_terms_v2`
- `edit_audit_log_v2`
- `upload_jobs_v2`

## Legacy Compatibility Tables (Do Not Expand)
These are legacy-only compatibility tables. Keep them readable during transition but do not build new features on them:

- `uploads`
- `employees`
- `schedule_entries`

## Route Classification (app.py)

### V2-ready
- `/api/v2/analytics`
- `/api/v2/issues`
- `/api/v2/issues/resolve`
- `/api/v2/dictionary` (GET/POST)
- `/api/v2/jobs`
- `/api/upload` (default flow with `USE_V2_PARSER=True`)
- `/api/group_summary`
- `/api/export`

### V1 legacy
- `/api/validation` (reads `uploads`)
- `/api/schedule_stats` (reads `schedule_entries`)
- `/api/schedule_entries` (reads `schedule_entries`)
- `/api/schedule_export` (reads `schedule_entries`)

### Mixed/risky
- `/api/stats`
  - Dual-path behavior (`USE_V2_PARSER` switch) can produce different dashboard totals and grouping logic depending on config.
- `/api/delete_all`
  - Intentionally deletes both V1 and V2 tables for cleanup consistency.
- `/api/delete_group`
  - Intentionally deletes both V1 and V2 tables for cleanup consistency.
- `/` (UI route)
  - Frontend currently surfaces both V2 and schedule features; schedule APIs still point to legacy table.

## Guardrails
- Do not add new writes to `uploads`, `employees`, or `schedule_entries` unless explicitly needed for temporary compatibility.
- Prefer all new analytics, validation, and exports from V2 tables only.
- Keep dictionary data in `dictionary_terms_v2`; do not duplicate in V1.
- Keep deletion APIs cross-version until V1 routes are retired.

## Recommended Route-Conversion Order
1. Convert `/api/stats` to V2-only response contract and remove V1 branch.
2. Replace `/api/validation` with V2 validation view (from `validation_issues_v2` and bill-level checks).
3. Decide schedule strategy:
   - either migrate schedules to V2 schema, or
   - explicitly mark schedule APIs as legacy and hide from primary UI.
4. After schedule decision, convert/remove:
   - `/api/schedule_stats`
   - `/api/schedule_entries`
   - `/api/schedule_export`
5. Keep `/api/delete_all` and `/api/delete_group` dual-delete until no V1 tables are used by any route/UI path.
6. Final cleanup phase (separate change): retire V1 routes and tables only after UI and tests are fully V2.

## Notes For Future Prompts
- Treat V2 tables as authoritative.
- Avoid introducing new mixed V1/V2 queries.
- Parser accuracy fixes are separate from source-of-truth migration and should not change route ownership decisions.
