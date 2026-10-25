# Implementation ledger
Plan: docs/superpowers/plans/2026-10-26-unified-ifms.md
Approved design preserved. Existing isolated checkout; feature branch created; archive source originals retained.
Ruling: preserve existing inner application as compatibility interface while adding suite routes, to avoid regression in schedules and monthly comparison.
Tasks: 1 in progress; 2–5 pending.

First implementation checkpoint:
- Source imported from archives without personal databases or live documents; originals retained.
- Task 1 signed ROP and zero-cash regression tests RED -> GREEN.
- Task 2 inclusive calendar percentage calculation tests RED -> GREEN; limited first engine, other allowance bases pending.
- Tasks 3/4 started: shared tables, claims, manual rates, conservative GA55 parser, import review endpoints, local OCR adapter, PDF/XLSX export, unified sidebar.
- 17 targeted tests pass. Actual supplied GA55 produces 16 candidate payments and signed ROP -6047.
- Actual app suite and retained analyzer routes return 200; retained health returns 200.
- Full suite after restoring private fixture PDFs: 70 passed, 14 skipped, 14 failed. Thirteen V1 expected-deduction regressions are in byte-identical inherited parser.py (SHA256 09b1c2b39ebd7ef98b24ce585568bc7e2dad65bb84a6fe8747bf4c1d16c35e4d); missing start_tool.sh fixed in this checkpoint, recheck pending.
- Ruling: 2-decimal HALF_UP for initial calendar engine, due and drawn separately; leap-day difference is 34.49, not rounded rate-difference 34.48. Government whole-rupee and other proration policies remain to implement and verify.
- Runtime Python development environment measured 318 MB on Linux. This is not a Windows installer measurement or evidence of sub-500 MB compliance.
- Official rates and current SheetJS download blocked by network policy; need targeted domain additions. Never mark manual rates official.
Outstanding: complete allowance rules/pay timeline, group shared-data UI, GA55 review UI and imports to drawn history, previous-settlement allocation, deductions, batch workflow, exact form templates, rates verification, full Windows packaging and regression acceptance. No production-readiness claim.

Review fixes: case/date normalization for duplicate claims; spreadsheet formula protection; finalized rate/drawn references in exports; explicit draft PDF labeling; settlement rounded before arithmetic; reviewed imports cannot be OCR-reprocessed; review metadata cannot relabel the immutable calculation. Every issue reproduced RED then GREEN. 22 targeted tests pass.
Independent reviewer: review_integration (read-only).
Startup support: launch.py binds 127.0.0.1 and opens /suite/; start_workspace.bat creates local venv with pinned dependencies. Existing start_tool.bat retained for compatibility. Linux startup helper added.
Cloud config draft saved install_script/start_skill and targeted domains finance.rajasthan.gov.in and cdn.sheetjs.com. Requires user review/save and publication; draft save does not change runtime access. GitHub API read denied in current environment, while native Git reads work. No token requested.
Additional review fixes: zero-net arrear still checks gross/deduction arithmetic; BEGIN IMMEDIATE serializes overlapping finalization. Both reproduced RED, then GREEN including eight concurrent finalization requests. Targeted suite: 24 passed.
Last full regression run (before final two review tests): 80 passed, 14 skipped, 13 failed. All 13 failures are tests/test_expected_totals.py for inherited V1 deduction totals in 1.pdf–13.pdf; V2 and new suite gates pass. Original parser.py remains byte-identical to archive. Failures are retained and not hidden.
Actual HTTP checks: /suite/, /suite/static/suite.js, /analyzer, /api/v3/health_check all return 200 on loopback; node --check suite.js passes.
Development checkpoint pushed to GitHub branch feat/unified-ifms at 6bd0f09. GitHub API unavailable so no pull request created; branch push succeeded via existing Git authentication.
