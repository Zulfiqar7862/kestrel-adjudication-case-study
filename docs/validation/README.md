# Validation archive

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current evidence-chain fix

[Evidence-chain review](evidence-chain-review/report.md): test-first file/index
reconciliation and guarded consumers; 235 tests pass; unchanged 0/290/130 counts,
28/392 notification split, 420 identical replays and 8 untouched chains.
[Current testing guide](../06-testing-and-validation.md).

## Retained historical reports

These reports are versioned experiment records, not a single current specification.
Read the stated baseline/version before quoting any count or implementation claim.
Raw failures, outputs and source observations are preserved, not silently rewritten.

- [Documentation/visuals, baseline 62c498f](documentation-review/report.md)
- [Notification obligations, 0.5.1](notification-obligations-review/report.md)
- [Initial independent notification lane, 0.5.0](evidence-workflows/02-notifications.md)
- [Historical candidates separated from closures, 0.4.3](historical-candidates-review/report.md)
- [Storage limits and 86-case table, 0.4.2](storage-limits-review/report.md)
- [Earlier correctness changes, 0.4.1](correctness-review/report.md)

Earlier JSON/CSV/log artifacts remain in this directory. They are historical
comparisons, not production accuracy evidence or targets for optimising counts.
