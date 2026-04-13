# Nexus OS A2A Bridge Protocol Specification v1.0

## Overview

The Nexus OS Bridge is a JSON-RPC 2.0 over HTTP endpoint that serves as the
central gateway for all agent-to-agent (A2A) communication. Every request must
pass through authentication (HMAC-SHA256), authorization (KAIJU 4-variable),
and compliance checks before execution.

## Request Format

All requests use HTTP POST with JSON body.

### Required Headers

| Header | Description | Example |
|--------|-------------|---------|
| `Content-Type` | Must be `application/json` | `application/json` |
| `X-Nexus-Project-ID` | Target project scope | `proj-001` |
| `X-Nexus-Agent-ID` | Calling agent identifier | `glm5-worker-1` |
| `X-Nexus-Trace-ID` | Unique trace for audit trail | `a1b2c3d4e5f67890` |
| `X-Nexus-Signature` | HMAC-SHA256 signature (64 hex chars) | `f7a3b9c2...` |

### Optional Headers

| Header | Description |
|--------|-------------|
| `X-Nexus-Lineage-ID` | Chain ID for sequential request workflows |

## Authentication Flow

1. Agent generates signature: `HMAC-SHA256(secret, "{secret}:{trace_id}:{payload}")`
2. Agent sends signature in `X-Nexus-Signature` header.
3. Server looks up agent secret from `SecretStore` (env var `NEXUS_SECRET_{AGENT_ID}`).
4. Server recomputes signature and compares using `hmac.compare_digest()`.
5. If mismatch or missing → **401 Unauthorized**.

## Authorization Flow (KAIJU 4-Variable)

After authentication passes, the request is authorized via `NexusGovernor.check_access()`:

1. Extract KAIJU variables from request payload `kaiju` object:
   - `scope` — SELF, PROJECT, CROSS_PROJECT, SYSTEM
   - `intent` — free-text justification (10+ chars for destructive actions)
   - `impact` — LOW, MEDIUM, HIGH, CRITICAL
   - `clearance` — READER, CONTRIBUTOR, MAINTAINER, ADMIN

2. Run `KaijuAuthorizer.authorize(AuthRequest(...))`.

3. Decision mapping:
   - `ALLOW` → Proceed to execution → **200 OK**
   - `DENY` → **403 Forbidden** with error reason
   - `HOLD` → **202 Accepted** with hold ticket (trace_id)

## Endpoints

### POST `/tasks/submit`

Submit a task for execution.

**Request body:**
```json
{
  "description": "Review the authentication module",
  "context": {"type": "code_review"},
  "kaiju": {
    "scope": "project",
    "intent": "review authentication code for security issues",
    "impact": "low",
    "clearance": "contributor"
  }
}
```

**Success response (200):**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": "task-uuid-001",
    "status": "completed",
    "output": "Mock execution #1: Review the authentication module",
    "duration_ms": 10.5
  },
  "trace_id": "a1b2c3d4e5f67890"
}
```

**HOLD response (202):**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": null,
    "status": "held",
    "hold_reason": "HOLD: Intent is empty or too short",
    "hold_ticket": "a1b2c3d4e5f67890"
  },
  "trace_id": "a1b2c3d4e5f67890"
}
```

### POST `/tasks/status`

Query task status.

**Request body:**
```json
{"task_id": "task-uuid-001"}
```

### POST `/vault/read`

Query Vault memory.

**Request body:**
```json
{"query": "authentication design", "type": "project", "limit": 10}
```

### POST `/vault/write`

Write to Vault memory.

**Request body:**
```json
{"content": "Memory content here", "type": "project", "classification": "standard"}
```

## Error Codes

| HTTP Status | Code | Meaning |
|-------------|------|---------|
| 200 | `OK` | Request completed successfully |
| 202 | `HELD` | Request held for human review |
| 400 | `PARSE_ERROR` | Malformed JSON body |
| 401 | `AUTH_FAILED` | Missing or invalid HMAC signature |
| 403 | `FORBIDDEN` | KAIJU authorization denied |
| 404 | `NOT_FOUND` | Endpoint not found |
| 405 | `METHOD_NOT_ALLOWED` | Non-POST request |
| 500 | `INTERNAL_ERROR` | Server-side exception |

**Error response format:**
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": 401,
    "message": "Authentication failed: missing X-Nexus-Signature header",
    "data": null
  },
  "trace_id": "a1b2c3d4e5f67890"
}
```

## Signature Algorithm

```
message = "{secret}:{trace_id}:{payload_json_string}"
signature = HMAC-SHA256(secret_bytes, message_bytes) → hex digest (64 chars)
```

Where `payload_json_string` is the JSON-serialized request body (deterministic).
