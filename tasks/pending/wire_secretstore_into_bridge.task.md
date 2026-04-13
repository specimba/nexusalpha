---
id: task-004
type: feature
priority: high
status: pending
assigned_to: Nexus-Execution
created: 2026-04-13T00:00:00Z
---
# Task: Wire SecretStore Into Bridge

## Description
Replace the hardcoded `AGENT_SECRETS` dictionary in `bridge/server.py` with the `SecretStore` class from `bridge/secrets.py`. Use the 4-tier lookup.

## Acceptance Criteria
- [ ] `AGENT_SECRETS` is removed from `bridge/server.py`
- [ ] `SecretStore` from `bridge/secrets.py` is used instead
- [ ] The 4-tier lookup is implemented in the bridge path
- [ ] `pytest tests/unit/test_secrets.py` passes
