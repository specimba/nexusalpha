"""Tests for Bridge Token Headers."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from nexus_os.bridge.server import jsonrpc_result

def test_jsonrpc_has_token_headers():
    res = jsonrpc_result({"data": "ok"}, trace_id="tr-123", input_tokens=50, output_tokens=100)
    assert "x-nexus-input-tokens" in res
    assert res["x-nexus-input-tokens"] == 50
    assert "x-nexus-output-tokens" in res
    assert res["x-nexus-output-tokens"] == 100
    assert res["trace_id"] == "tr-123"
