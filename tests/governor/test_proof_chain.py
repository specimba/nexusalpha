"""Tests for VAP Proof Chain integrity."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from nexus_os.governor.proof_chain import ProofChain

def test_vap_chain_creation():
    chain = ProofChain()
    assert chain.verify_chain() == True
    assert len(chain._entries) == 0

def test_vap_chain_record_and_verify():
    chain = ProofChain()
    r1 = chain.record("agent-1", "read", {"res": "doc-1"})
    r2 = chain.record("agent-2", "write", {"res": "doc-1"})
    
    assert len(chain._entries) == 2
    assert chain.verify_chain() == True
    assert r2.l2_hash != r1.l2_hash

def test_vap_chain_summary():
    chain = ProofChain()
    chain.record("agent-1", "auth", {})
    summary = chain.get_chain_summary()
    assert summary["total_entries"] == 1
    assert summary["chain_valid"] == True
