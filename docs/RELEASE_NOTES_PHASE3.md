# IFMS Report Analyzer - Phase 3 Release Notes

Build label: Phase3-Full-Stable

## Completed Phases

- Phase 1: Employee Data engine, validation review, filtered export, and manual QA support.
- Phase 2: Derived Schedule engine, Schedule QA, reconciliation, and unmapped component review.
- Phase 3A: Backup & Restore Center.
- Phase 3B: Export Center.
- Phase 3C: Official Schedule Comparison.
- Phase 3D: Monthly Comparison Engine.
- Phase 3E: Master Employee Register.
- Phase 3 Final: Release candidate diagnostics, health check, action inventory, help, and smoke hardening.

## Major Modules

- Upload PDFs
- Employee Data
- Dictionary and designation workflow
- Schedules
- Official Schedule Comparison
- Monthly Comparison
- Master Register
- Backup & Restore
- Export Center
- System Diagnostics
- Help / User Guide

## Safety Notes

- Human review is compulsory before using any data for official work.
- The app is designed to help increase office productivity.
- Master Register is an intelligence layer and does not replace official records.
- Monthly comparison is only as accurate as parsed Employee Data.
- Official schedule comparison supports mapped layouts; unknown layouts go to review.
- OCR is not included.
- The app is designed for local office productivity use.

## Backup Instruction

Create a full backup from Backup & Restore before:

- bulk upload,
- dictionary import,
- schedule mapping import,
- restore operation,
- release candidate validation,
- final office use.

## Restore Instruction

Use Backup & Restore only with a trusted backup ZIP from this app. Review the restored Employee Data, schedules, dictionary mappings, and exports before office use.

## Manual Testing Checklist

- Start the app successfully.
- Open `/api/version` and confirm `Phase3-Full-Stable`.
- Open `/api/v3/health_check` and confirm no critical errors.
- Create a backup.
- Open Upload PDFs.
- Open Employee Data and run one filter.
- Open Schedules.
- Open Official Schedule Comparison.
- Open Monthly Comparison.
- Open Master Register.
- Open Export Center.
- Open System Diagnostics.
- Open Help / User Guide.
- Run `python scripts/ui_smoke_check.py`.
- Run the V2/V3 regression tests.
- Confirm the manual review reminder is understood.

## Known Limitations

- Human review is compulsory.
- OCR is not included.
- Official schedule comparison supports mapped layouts; unknown layouts go to review.
- Monthly comparison is only as accurate as parsed Employee Data.
- Master Register is an intelligence layer and does not replace official records.
- The app is designed for local office productivity use.

## Next Planned Improvements

- Broader official schedule layout coverage.
- More guided issue triage for Master Register identity conflicts.
- Optional richer release dashboard after the release candidate is validated.
