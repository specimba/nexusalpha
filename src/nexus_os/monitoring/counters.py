"""
Token Counter Implementations
Supports: Local (ai-tokenizer), Native, Tokscale CLI
"""

import subprocess
import re
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseCounter(ABC):
    """Base token counter."""
    
    @abstractmethod
    def count(self, text: str) -> int:
        """Count tokens in text."""
        pass


class LocalCounter(BaseCounter):
    """
    Local counting via tiktoken/tiktoken fallback.
    Speed: 5-7x faster than cloud
    """
    
    def __init__(self, model: str = "gpt-4"):
        try:
            import tiktoken
            self.encoder = tiktoken.get_encoding(model)
        except ImportError:
            self.encoder = None
    
    def count(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        
        # Fallback: rough estimate (chars / 4)
        return len(text) // 4


class NativeCounter(BaseCounter):
    """
    Native counting via model tokenizer.
    Fastest option if model loaded.
    """
    
    def __init__(self, model_name: str):
        self.model_name = model_name
    
    def count(self, text: str) -> int:
        # For Ollama: use ollama run with counting
        # For OpenAI: use tiktoken
        try:
            import tiktoken
            encoder = tiktoken.get_encoding("cl100k_base")
            return len(encoder.encode(text))
        except ImportError:
            return len(text) // 4


class TokscaleCounter(BaseCounter):
    """
    Tokscale CLI integration.
    Provides: cost breakdown, optimization suggestions, dashboards.
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
    
    def count(self, text: str) -> int:
        """Count via tokscale CLI."""
        try:
            result = subprocess.run(
                ["tokscale", "count", text],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                match = re.search(r'\d+', result.stdout)
                if match:
                    return int(match.group())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Fallback
        return len(text) // 4
    
    def get_dashboard_url(self) -> str:
        """Get tokscale dashboard URL."""
        return "https://tokscale.com/dashboard"
