#!/usr/bin/env python3
import sys
sys.path.insert(0, "src")

def test_all():
    try:
        from nexus_os.governor.proof_chain import ProofChain
        from nexus_os.monitoring.token_guard import TokenGuard
        
        # Test ProofChain
        chain = ProofChain()
        chain.record("agent-1", "read", {})
        assert chain.verify_chain()
        print("✅ P0-4 VAP Chain OK")
        
        # Test TokenGuard check
        guard = TokenGuard()
        assert guard.check("agent-1", 100)
        print("✅ P0-2 TokenGuard Check OK")
        
        print("🎉 All P0 Components Present")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_all()
