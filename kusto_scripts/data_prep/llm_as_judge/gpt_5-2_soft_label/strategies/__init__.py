"""
Strategies Module
=================

Labeling strategies that define what input the LLM judge sees.

Different strategies may produce different labels because the LLM
sees different context. This allows experimentation with:

1. user_message_only (Strategy A):
   - LLM sees ONLY the user message, in isolation
   - No conversation context, no model response
   - Simplest and cheapest strategy
   
2. Future strategies (not yet implemented):
   - with_context: Include previous turns
   - with_response: Include the model's response
   - with_metadata: Include turn count, tools used, etc.

Why Multiple Strategies?
    The "correct" label may depend on context. A message like
    "now sort it" is simple in isolation but may require reasoning
    when you consider the full conversation context.
    
    By comparing labels from different strategies, you can:
    - Identify context-dependent messages
    - Choose the best strategy for your use case
    - Create ensemble labels
"""

from .base import LabelingStrategy, StrategyResult
from .user_message_only import UserMessageOnlyStrategy

# Registry of available strategies
STRATEGIES = {
    "user_message_only": UserMessageOnlyStrategy,
}

def get_strategy(name: str) -> LabelingStrategy:
    """
    Get a labeling strategy by name.
    
    Args:
        name: Strategy name (e.g., "user_message_only")
    
    Returns:
        Strategy instance
    
    Raises:
        ValueError: If strategy name is unknown
    """
    if name not in STRATEGIES:
        available = ", ".join(STRATEGIES.keys())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
    
    return STRATEGIES[name]()


__all__ = [
    "LabelingStrategy",
    "StrategyResult",
    "UserMessageOnlyStrategy",
    "STRATEGIES",
    "get_strategy",
]

