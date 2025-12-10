"""
Configuration module for LLM-as-Judge.
"""

from .azure_foundry import get_anthropic_client, get_model_name, get_api_key
from .settings import config, Config

__all__ = [
    "get_anthropic_client",
    "get_model_name", 
    "get_api_key",
    "config",
    "Config"
]

