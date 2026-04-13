"""
PATCH: bridge/server.py — Wire SecretStore

Replace hardcoded AGENT_SECRETS dict with the SecretStore module.
Apply this diff to your existing bridge/server.py file.

BEFORE:
-------
AGENT_SECRETS = {
    "reviewer-01": "hardcoded_secret_abc",
    "coder-01": "hardcoded_secret_def",
    # ... more hardcoded secrets (SECURITY RISK)
}

async def verify_bridge_headers(request: Request):
    headers = {
        "project_id": request.headers.get("X-Nexus-Project-ID"),
        "agent_id": request.headers.get("X-Nexus-Agent-ID"),
        "trace_id": request.headers.get("X-Nexus-Trace-ID"),
        "signature": request.headers.get("X-Nexus-Signature"),
        "lineage_id": request.headers.get("X-Nexus-Lineage-ID"),
    }
    secret = AGENT_SECRETS.get(headers["agent_id"])
    if not secret:
        raise HTTPException(401, "Unknown agent")
    # ... rest of verification

AFTER:
------
from nexus_os.bridge.secrets import SecretStore, verify_signature

secret_store = SecretStore(
    secret_file="agents.json",
    master_key=os.environ.get("NEXUS_MASTER_KEY")
)

async def verify_bridge_headers(request: Request):
    headers = {
        "project_id": request.headers.get("X-Nexus-Project-ID"),
        "agent_id": request.headers.get("X-Nexus-Agent-ID"),
        "trace_id": request.headers.get("X-Nexus-Trace-ID"),
        "signature": request.headers.get("X-Nexus-Signature"),
        "lineage_id": request.headers.get("X-Nexus-Lineage-ID"),
    }

    if not headers["agent_id"] or not headers["trace_id"]:
        raise HTTPException(400, "Missing agent_id or trace_id")

    try:
        secret = secret_store.get_secret(headers["agent_id"])
    except SecretNotFoundError:
        raise HTTPException(401, f"Unknown agent: {headers['agent_id']}")

    body = await request.body()
    if not verify_signature(secret, headers["trace_id"], body.decode(), headers["signature"]):
        raise HTTPException(401, "Invalid signature")

    return headers
"""

# Also create the agents.json template
AGENTS_JSON_TEMPLATE = """{
    "reviewer-01": "CHANGE_ME_IN_PRODUCTION",
    "coder-01": "CHANGE_ME_IN_PRODUCTION",
    "verifier-01": "CHANGE_ME_IN_PRODUCTION"
}
"""
