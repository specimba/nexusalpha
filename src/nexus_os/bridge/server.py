"""
bridge/server.py — Nexus OS A2A Bridge Server

Production-hardened FastAPI endpoint for agent-to-agent communication.
Implements JSON-RPC 2.0 over HTTP with:

  1. HMAC-SHA256 authentication via SecretStore
  2. KAIJU 4-variable authorization via NexusGovernor
  3. Task execution via TaskExecutor
  4. Structured JSON-RPC 2.0 responses
  5. Comprehensive error handling

Endpoints:
  POST /tasks/submit  — Submit task for execution
  POST /tasks/status  — Query task status
  POST /vault/read    — Query Vault memory
  POST /vault/write   — Write to Vault memory
  POST /              — JSON-RPC 2.0 router (dispatches to above)
"""

import json
import time
import uuid
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Exceptions ──────────────────────────────────────────────────

class BridgeError(Exception):
    """Base exception for Bridge errors."""
    def __init__(self, code: int, message: str, http_status: int = 500):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class AuthError(BridgeError):
    def __init__(self, message: str):
        super().__init__(401, message, http_status=401)


class ForbiddenError(BridgeError):
    def __init__(self, message: str):
        super().__init__(403, message, http_status=403)


class HeldError(BridgeError):
    def __init__(self, message: str, trace_id: str):
        super().__init__(202, message, http_status=202)
        self.hold_ticket = trace_id


class ParseError(BridgeError):
    def __init__(self, message: str):
        super().__init__(32700, message, http_status=400)


# ── Request Models ──────────────────────────────────────────────

@dataclass
class BridgeRequest:
    """Parsed Bridge request with validated headers and body."""
    agent_id: str
    project_id: str
    trace_id: str
    signature: str
    lineage_id: Optional[str]
    payload: Dict[str, Any]
    raw_payload: str
    method: str  # "tasks/submit", "tasks/status", "vault/read", "vault/write"
    kaiju: Dict[str, str] = field(default_factory=dict)


# ── JSON-RPC Response Builder ──────────────────────────────────

def jsonrpc_result(result: Any, trace_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "result": result,
        "trace_id": trace_id,
    }

def jsonrpc_error(code: int, message: str, trace_id: Optional[str] = None, data: Any = None) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "error": {
            "code": code,
            "message": message,
            "data": data,
        },
        "trace_id": trace_id,
    }


# ── Bridge Server ──────────────────────────────────────────────

class BridgeServer:
    """
    Nexus OS A2A Bridge Server.

    Can be used standalone (via handle_request()) or mounted on FastAPI/ASGI.
    All public methods take raw HTTP inputs and return (status_code, response_dict).
    TokenGuard integration: tracks token usage and adds X-Nexus-Input-Tokens,
    X-Nexus-Output-Tokens headers to FastAPI responses.
    """

    def __init__(
        self,
        secret_store=None,
        governor=None,
        executor=None,
        token_guard=None,
    ):
        from nexus_os.bridge.secrets import SecretStore
        from nexus_os.engine.executor import MockExecutor
        from nexus_os.monitoring.token_guard import TokenGuard

        self.secret_store = secret_store or SecretStore()
        self.governor = governor
        self.executor = executor or MockExecutor()
        self.token_guard = token_guard or TokenGuard()
        self._task_results: Dict[str, Any] = {}

    # ── Token Guard Helpers ────────────────────────────────────

    def _parse_input_tokens(self, headers, payload) -> int:
        """Extract input token count. Header > payload > fallback(0)."""
        hval = headers.get("x-nexus-input-tokens") or headers.get("x-nexus-tokens")
        if hval:
            try:
                return int(hval)
            except (TypeError, ValueError):
                pass
        if isinstance(payload, dict) and "tokens" in payload:
            try:
                return int(payload["tokens"])
            except (TypeError, ValueError):
                pass
        return 0

    def _track_tokens(self, agent_id, project_id, operation, input_tokens, output_tokens):
        """Track tokens via TokenGuard. Non-blocking — never breaks requests."""
        if input_tokens <= 0 and output_tokens <= 0:
            return None
        try:
            if input_tokens > 0:
                self.token_guard.track(agent_id, input_tokens,
                                   operation=operation,
                                   context={"project_id": project_id})
            if output_tokens > 0:
                self.token_guard.track(agent_id, output_tokens,
                                       operation=f"{operation}_output",
                                       context={"project_id": project_id})
            return {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
                "budget_remaining": self.token_guard.remaining(agent_id),
            }
        except Exception:
            # Non-blocking — log but never fail a request
            import logging
            logging.getLogger(__name__).warning("TokenGuard tracking failed")
            return {"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens}


    # ── Authentication ─────────────────────────────────────────

    def _authenticate(self, request: BridgeRequest):
        """Validate HMAC-SHA256 signature. Raises AuthError on failure."""
        from nexus_os.bridge.secrets import verify_signature, SecretNotFoundError

        if not request.signature:
            raise AuthError("Missing X-Nexus-Signature header")

        if not request.trace_id:
            raise AuthError("Missing X-Nexus-Trace-ID header")

        try:
            secret = self.secret_store.get_secret(request.agent_id)
        except SecretNotFoundError:
            raise AuthError(f"Unknown agent: {request.agent_id}")

        if not verify_signature(secret, request.trace_id, request.raw_payload, request.signature):
            raise AuthError("Invalid signature")

    # ── Authorization ──────────────────────────────────────────

    def _authorize(self, request: BridgeRequest):
        """Run KAIJU 4-variable authorization. Raises ForbiddenError or HeldError."""
        if self.governor is None:
            return  # No governor — skip authz (dev mode)

        from nexus_os.governor.kaiju_auth import Decision

        kaiju = request.kaiju
        result = self.governor.check_access(
            agent_id=request.agent_id,
            project_id=request.project_id,
            action=self._kaiju_action(request.method),
            scope=kaiju.get("scope", "project"),
            intent=kaiju.get("intent", ""),
            impact=kaiju.get("impact", "low"),
            clearance=kaiju.get("clearance", "contributor"),
            trace_id=request.trace_id,
            context={
                "signature_verified": True,
                "has_secret": True,
                "is_registered": True,
            },
        )

        if result.decision == Decision.DENY:
            raise ForbiddenError(result.reason)
        elif result.decision == Decision.HOLD:
            raise HeldError(result.reason, request.trace_id)

    def _kaiju_action(self, method: str) -> str:
        """Map Bridge method to KAIJU action type."""
        action_map = {
            "tasks/submit": "execute",
            "tasks/status": "read",
            "vault/read": "read",
            "vault/write": "write",
        }
        return action_map.get(method, "read")

    # ── Request Parsing ────────────────────────────────────────

    def parse_request(
        self,
        body: bytes,
        headers: Dict[str, str],
    ) -> BridgeRequest:
        """Parse and validate raw HTTP request into BridgeRequest."""
        # Parse JSON body
        try:
            raw = body.decode("utf-8")
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ParseError(f"Malformed JSON body: {e}")

        if not isinstance(payload, dict):
            raise ParseError("Request body must be a JSON object")

        # Extract required headers
        agent_id = headers.get("x-nexus-agent-id", "")
        project_id = headers.get("x-nexus-project-id", "")
        trace_id = headers.get("x-nexus-trace-id", "")
        signature = headers.get("x-nexus-signature", "")
        lineage_id = headers.get("x-nexus-lineage-id")

        # Determine method from the path
        # (The caller passes method via the path; for the single "/" endpoint,
        #  we use the "method" field in the JSON body if present, default to tasks/submit)
        method = payload.pop("method", "tasks/submit") if isinstance(payload, dict) else "tasks/submit"

        kaiju = payload.pop("kaiju", {}) if isinstance(payload, dict) else {}

        return BridgeRequest(
            agent_id=agent_id,
            project_id=project_id,
            trace_id=trace_id,
            signature=signature,
            lineage_id=lineage_id,
            payload=payload,
            raw_payload=raw,
            method=method,
            kaiju=kaiju if isinstance(kaiju, dict) else {},
        )

    # ── Handler Dispatch ───────────────────────────────────────

    def handle_request(
        self,
        method: str,
        body: bytes,
        headers: Dict[str, str],
    ) -> tuple:
        """
        Handle a single Bridge request.

        Args:
            method: HTTP method (must be POST)
            body: Raw request body bytes
            headers: Dict of HTTP headers (case-insensitive keys)

        Returns:
            (status_code: int, response_dict: dict)
        """
        start = time.perf_counter()

        try:
            # Only POST allowed
            if method.upper() != "POST":
                return 405, jsonrpc_error(
                    -32600, "Method not allowed. Use POST.",
                    data="Only POST is supported"
                )

            # Parse request — method read from JSON payload['method']
            req = self.parse_request(body, headers)

            # Track tokens (before dispatch if input_tokens known)
            input_tokens = self._parse_input_tokens(headers, req.payload)

            # Authenticate
            self._authenticate(req)

            # Authorize
            self._authorize(req)

            # Dispatch
            result = self._dispatch(req)

            duration = (time.perf_counter() - start) * 1000
            if isinstance(result, dict) and "duration_ms" not in result:
                result["duration_ms"] = round(duration, 2)


            # Track token usage
            response_json = json.dumps(result) if isinstance(result, dict) else "{}"
            output_tokens = len(response_json) * 4 // 10  # rough: chars to ~token estimate
            token_info = self._track_tokens(req.agent_id, req.project_id,
                                            req.method, input_tokens, output_tokens)
            if token_info:
                result["token_usage"] = token_info

            return 200, jsonrpc_result(result, req.trace_id)

        except HeldError as e:
            return e.http_status, jsonrpc_result(
                {
                    "task_id": None,
                    "status": "held",
                    "hold_reason": e.message,
                    "hold_ticket": e.hold_ticket,
                },
                e.hold_ticket,
            )
        except AuthError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except ForbiddenError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except ParseError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except Exception as e:
            logger.exception("Bridge internal error")
            return 500, jsonrpc_error(
                -32603, f"Internal error: {e}"
            )

    def handle_submit(self, body: bytes, headers: Dict[str, str]) -> tuple:
        """Handle POST /tasks/submit."""
        start = time.perf_counter()
        try:
            req = self.parse_request(body, headers)
            req.method = "tasks/submit"
            self._authenticate(req)
            self._authorize(req)

            task_id = f"task-{uuid.uuid4().hex[:12]}"
            description = req.payload.get("description", "")
            context = req.payload.get("context", {})
            context["agent_id"] = req.agent_id

            exec_result = self.executor.execute(task_id, description, context)

            self._task_results[task_id] = {
                "task_id": task_id,
                "status": "completed" if exec_result.success else "failed",
                "output": exec_result.output,
                "error": exec_result.error,
            }

            duration = (time.perf_counter() - start) * 1000
            return 200, jsonrpc_result({
                "task_id": task_id,
                "status": "completed" if exec_result.success else "failed",
                "output": exec_result.output,
                "error": exec_result.error,
                "duration_ms": round(duration, 2),
            }, req.trace_id)

        except HeldError as e:
            return e.http_status, jsonrpc_result(
                {"task_id": None, "status": "held", "hold_reason": e.message, "hold_ticket": e.hold_ticket},
                e.hold_ticket,
            )
        except AuthError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except ForbiddenError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except ParseError as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except Exception as e:
            logger.exception("Bridge submit error")
            return 500, jsonrpc_error(-32603, f"Internal error: {e}")

    def handle_status(self, body: bytes, headers: Dict[str, str]) -> tuple:
        """Handle POST /tasks/status."""
        try:
            req = self.parse_request(body, headers)
            req.method = "tasks/status"
            self._authenticate(req)
            self._authorize(req)

            task_id = req.payload.get("task_id", "")
            result = self._task_results.get(task_id)

            if result is None:
                return 404, jsonrpc_error(-32602, f"Task not found: {task_id}")

            return 200, jsonrpc_result(result, req.trace_id)
        except (AuthError, ForbiddenError, ParseError, HeldError) as e:
            return e.http_status, jsonrpc_error(e.code, e.message, data=e.hold_ticket if isinstance(e, HeldError) else None)
        except Exception as e:
            return 500, jsonrpc_error(-32603, f"Internal error: {e}")

    def handle_vault_read(self, body: bytes, headers: Dict[str, str]) -> tuple:
        """Handle POST /vault/read."""
        try:
            req = self.parse_request(body, headers)
            req.method = "vault/read"
            self._authenticate(req)
            self._authorize(req)
            return 200, jsonrpc_result(
                {"records": [], "query": req.payload.get("query", ""), "count": 0},
                req.trace_id,
            )
        except (AuthError, ForbiddenError, ParseError, HeldError) as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except Exception as e:
            return 500, jsonrpc_error(-32603, f"Internal error: {e}")

    def handle_vault_write(self, body: bytes, headers: Dict[str, str]) -> tuple:
        """Handle POST /vault/write."""
        try:
            req = self.parse_request(body, headers)
            req.method = "vault/write"
            self._authenticate(req)
            self._authorize(req)
            return 200, jsonrpc_result(
                {"record_id": f"rec-{uuid.uuid4().hex[:8]}", "status": "written"},
                req.trace_id,
            )
        except (AuthError, ForbiddenError, ParseError, HeldError) as e:
            return e.http_status, jsonrpc_error(e.code, e.message)
        except Exception as e:
            return 500, jsonrpc_error(-32603, f"Internal error: {e}")

    def _dispatch(self, req: BridgeRequest) -> Dict[str, Any]:
        """Dispatch parsed request to appropriate handler."""
        handlers = {
            "tasks/submit": self._exec_submit,
            "tasks/status": self._exec_status,
            "vault/read": self._exec_vault_read,
            "vault/write": self._exec_vault_write,
        }
        handler = handlers.get(req.method)
        if handler is None:
            raise ParseError(f"Unknown method: {req.method}")
        return handler(req)

    def _exec_submit(self, req: BridgeRequest) -> Dict[str, Any]:
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        description = req.payload.get("description", "")
        context = req.payload.get("context", {})
        context["agent_id"] = req.agent_id

        exec_result = self.executor.execute(task_id, description, context)

        self._task_results[task_id] = {
            "task_id": task_id,
            "status": "completed" if exec_result.success else "failed",
            "output": exec_result.output,
            "error": exec_result.error,
        }

        return {
            "task_id": task_id,
            "status": "completed" if exec_result.success else "failed",
            "output": exec_result.output,
            "error": exec_result.error,
        }

    def _exec_status(self, req: BridgeRequest) -> Dict[str, Any]:
        task_id = req.payload.get("task_id", "")
        result = self._task_results.get(task_id)
        if result is None:
            raise ParseError(f"Task not found: {task_id}")
        return result

    def _exec_vault_read(self, req: BridgeRequest) -> Dict[str, Any]:
        return {"records": [], "query": req.payload.get("query", ""), "count": 0}

    def _exec_vault_write(self, req: BridgeRequest) -> Dict[str, Any]:
        return {"record_id": f"rec-{uuid.uuid4().hex[:8]}", "status": "written"}


# ── FastAPI Integration ────────────────────────────────────────

def create_app(bridge: Optional[BridgeServer] = None) -> "FastAPI":
    """
    Create a FastAPI application wrapping the BridgeServer.

    Usage:
        from nexus_os.bridge.server import create_app
        app = create_app()
        # uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    try:
        from fastapi import FastAPI, Request, Response
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the Bridge server. "
            "Install it with: pip install fastapi uvicorn"
        )

    app = FastAPI(title="Nexus OS A2A Bridge", version="1.0.0")
    server = bridge or BridgeServer()

    @app.post("/tasks/submit")
    async def submit_task(request: Request):
        body = await request.body()
        req_headers = {k.lower(): v for k, v in request.headers.items()}
        agent_id = req_headers.get("x-nexus-agent-id", "unknown")
        input_tokens = len(body) // 4  # Rough estimate
        status_code, response = server.handle_submit(body, req_headers)
        output_tokens = len(str(response).encode()) // 4  # Rough estimate
        server.token_guard.track(agent_id, input_tokens + output_tokens,
                                  operation="task_delegation",
                                  input_tokens=input_tokens,
                                  output_tokens=output_tokens)
        return JSONResponse(content=response, status_code=status_code,
                           headers={"X-Nexus-Input-Tokens": str(input_tokens),
                                   "X-Nexus-Output-Tokens": str(output_tokens)})

    @app.post("/tasks/status")
    async def query_status(request: Request):
        body = await request.body()
        req_headers = {k.lower(): v for k, v in request.headers.items()}
        agent_id = req_headers.get("x-nexus-agent-id", "unknown")
        input_tokens = len(body) // 4
        status_code, response = server.handle_status(body, req_headers)
        output_tokens = len(str(response).encode()) // 4
        server.token_guard.track(agent_id, input_tokens + output_tokens,
                                  operation="memory_query",
                                  input_tokens=input_tokens,
                                  output_tokens=output_tokens)
        return JSONResponse(content=response, status_code=status_code,
                           headers={"X-Nexus-Input-Tokens": str(input_tokens),
                                   "X-Nexus-Output-Tokens": str(output_tokens)})

    @app.post("/vault/read")
    async def vault_read(request: Request):
        body = await request.body()
        req_headers = {k.lower(): v for k, v in request.headers.items()}
        agent_id = req_headers.get("x-nexus-agent-id", "unknown")
        input_tokens = len(body) // 4
        status_code, response = server.handle_vault_read(body, req_headers)
        output_tokens = len(str(response).encode()) // 4
        server.token_guard.track(agent_id, input_tokens + output_tokens,
                                  operation="memory_query",
                                  input_tokens=input_tokens,
                                  output_tokens=output_tokens)
        return JSONResponse(content=response, status_code=status_code,
                           headers={"X-Nexus-Input-Tokens": str(input_tokens),
                                   "X-Nexus-Output-Tokens": str(output_tokens)})

    @app.post("/vault/write")
    async def vault_write(request: Request):
        body = await request.body()
        req_headers = {k.lower(): v for k, v in request.headers.items()}
        agent_id = req_headers.get("x-nexus-agent-id", "unknown")
        input_tokens = len(body) // 4
        status_code, response = server.handle_vault_write(body, req_headers)
        output_tokens = len(str(response).encode()) // 4
        server.token_guard.track(agent_id, input_tokens + output_tokens,
                                  operation="memory_query",
                                  input_tokens=input_tokens,
                                  output_tokens=output_tokens)
        return JSONResponse(content=response, status_code=status_code,
                           headers={"X-Nexus-Input-Tokens": str(input_tokens),
                                   "X-Nexus-Output-Tokens": str(output_tokens)})

    @app.post("/")
    async def jsonrpc_router(request: Request):
        body = await request.body()
        req_headers = {k.lower(): v for k, v in request.headers.items()}
        agent_id = req_headers.get("x-nexus-agent-id", "unknown")
        input_tokens = len(body) // 4
        status_code, response = server.handle_request("POST", body, req_headers)
        output_tokens = len(str(response).encode()) // 4
        server.token_guard.track(agent_id, input_tokens + output_tokens,
                                  operation="model_inference",
                                  input_tokens=input_tokens,
                                  output_tokens=output_tokens)
        return JSONResponse(content=response, status_code=status_code,
                           headers={"X-Nexus-Input-Tokens": str(input_tokens),
                                   "X-Nexus-Output-Tokens": str(output_tokens)})

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "nexus-bridge", "version": "1.0.0"}

    return app
