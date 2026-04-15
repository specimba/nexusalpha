---
id: task-003
type: bugfix
priority: critical
status: pending
assigned_to: Nexus-Execution
created: 2026-04-13T00:00:00Z
---
# Task: Fix Encryption Hardfail Regression

## Description
Fix the silent encryption fallback in `db/manager.py`. Ensure that if encryption fails and `allow_unencrypted=False`, an `ImportError` is raised. Add the `test_encryption_hardfail.py` test to the suite.

## Acceptance Criteria
- [ ] Silent encryption fallback is removed in `db/manager.py`
- [ ] An `ImportError` is raised when encryption fails and `allow_unencrypted=False`
- [ ] `test_encryption_hardfail.py` is added to the test suite
- [ ] `pytest tests/security/test_encryption_hardfail.py` passes
