"""
TokenGuard Tests
Nexus OS v3.0 - Token Monitoring Layer
"""

import pytest
from src.nexus_os.monitoring.token_guard import TokenGuard


class TestTokenGuard:
    """TokenGuard unit tests."""
    
    def test_init_default_budgets(self):
        """Test default budget initialization."""
        guard = TokenGuard()
        status = guard.get_status()
        
        assert 'agent' in status
        assert 'skill' in status
        assert 'swarm' in status
        assert status['agent']['used'] == 0
    
    def test_init_custom_budgets(self):
        """Test custom budget initialization."""
        guard = TokenGuard(budgets={'agent': 100000})
        status = guard.get_status()
        
        assert status['agent']['total'] == 100000
    
    def test_track(self):
        """Test token tracking."""
        guard = TokenGuard()
        result = guard.track('test-agent', 100)
        
        assert result['tokens'] == 100
        assert result['agent_id'] == 'test-agent'
    
    def test_check_with_sufficient_budget(self):
        """Test budget check with sufficient tokens."""
        guard = TokenGuard(budgets={'agent': 50000})
        assert guard.check('agent', 10000) is True
    
    def test_check_with_insufficient_budget(self):
        """Test budget check with insufficient tokens."""
        guard = TokenGuard(budgets={'agent': 5000})
        assert guard.check('agent', 10000) is False
    
    def test_check_and_reserve_allowed(self):
        """Test atomic reserve when budget available."""
        guard = TokenGuard(budgets={'agent': 50000})
        result = guard.check_and_reserve('agent', 1000)
        
        assert result['allowed'] is True
        assert 'reservation_id' in result
    
    def test_check_and_reserve_denied(self):
        """Test atomic reserve when budget exceeded."""
        guard = TokenGuard(budgets={'agent': 100})
        result = guard.check_and_reserve('agent', 500)
        
        assert result['allowed'] is False
        assert result['reason'] == 'budget_exceeded'
    
    def test_audit_trail(self):
        """Test VAP-compliant audit trail."""
        guard = TokenGuard()
        guard.track('test', 100, input_tokens=50, output_tokens=50)
        
        entries = guard.get_audit(limit=10)
        assert len(entries) >= 1
        assert entries[-1]['actor'] == 'test'
    
    def test_semantic_cache_set_get(self):
        """Test semantic cache."""
        guard = TokenGuard()
        guard.semantic_cache_set('query1', {'result': 'data'})
        
        result = guard.semantic_cache_get('query1')
        assert result == {'result': 'data'}
    
    def test_route_simple_task(self):
        """Test model routing for simple task."""
        guard = TokenGuard()
        model = guard.route('code', 'low')
        
        assert model in ['qwen3:4b-thinking', 'osman-speed']
    
    def test_route_complex_task(self):
        """Test model routing for complex task."""
        guard = TokenGuard()
        model = guard.route('code', 'high', budget_remaining=100000)
        
        assert model in ['gpt-5.4', 'gemini-3.1-pro']
    
    def test_trigger_fallback(self):
        """Test fallback to cheaper model."""
        guard = TokenGuard()
        result = guard.trigger_fallback('osman-agent')
        
        assert result['original_agent'] == 'osman-agent'
        assert 'fallback_agent' in result
    
    def test_reset_budget(self):
        """Test budget reset."""
        guard = TokenGuard(budgets={'agent': 50000})
        guard.track('agent', 10000)
        
        assert guard.get_status('agent')['used'] == 10000
        
        guard.reset_budget('agent')
        assert guard.get_status('agent')['used'] == 0
    
    def test_analyze_trends(self):
        """Test trend analysis."""
        guard = TokenGuard()
        
        # Track some tokens
        for _ in range(5):
            guard.track('test-agent', 100)
        
        trends = guard.analyze_trends('test-agent', '1h')
        assert 'period' in trends
        assert trends['total_tokens'] >= 500


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
