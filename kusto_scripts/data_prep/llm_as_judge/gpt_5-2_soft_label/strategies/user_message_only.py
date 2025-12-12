"""
User Message Only Strategy (Strategy A)
========================================

The simplest labeling strategy: classify each user message in isolation.

What the LLM Sees:
    ONLY the user message text. No conversation context, no model
    response, no metadata about turn position or tools.

Use Case:
    - Baseline classification
    - When context doesn't matter for the task
    - Cheapest option (minimal tokens)

Example:
    Conversation:
        Turn 1: "Create a Python class for a bank account"
        Turn 2: "Add a withdraw method"
        Turn 3: "Now add overdraft protection"
    
    Strategy A labels each in isolation:
        Turn 1: "Create a Python class for a bank account" → classify alone
        Turn 2: "Add a withdraw method" → classify alone
        Turn 3: "Now add overdraft protection" → classify alone
    
    Note: Turn 2 and 3 might get different labels than if context
    was included, since "Add a withdraw method" is vague without
    knowing what we're adding it to.
"""

from .base import LabelingStrategy, StrategyResult
from ..io.schemas import TurnRecord


class UserMessageOnlyStrategy(LabelingStrategy):
    """
    Classify each user message in isolation.
    
    This is the simplest and cheapest strategy. The LLM sees only
    the user message text, with no conversation context or metadata.
    
    Pros:
        - Cheapest (minimal tokens)
        - Fastest (no context to process)
        - Consistent (same message always gets same input)
    
    Cons:
        - May misclassify context-dependent messages
        - "Add a method" is vague without context
        - Follow-up questions may seem simpler than they are
    
    Example:
        >>> strategy = UserMessageOnlyStrategy()
        >>> result = strategy.apply(turn)
        >>> print(result.text_to_classify)
        "How do I create a list in Python?"
    """
    
    @property
    def name(self) -> str:
        return "user_message_only"
    
    @property
    def description(self) -> str:
        return (
            "Classify each user message in isolation. "
            "The LLM sees ONLY the user message text, with no conversation "
            "context, model response, or metadata."
        )
    
    def extract_text(self, turn: TurnRecord) -> str:
        """
        Extract just the user message.
        
        Args:
            turn: The turn record
        
        Returns:
            The user message text only
        """
        return turn.user_message
    
    def _get_metadata(self, turn: TurnRecord) -> dict:
        """Include basic turn info in metadata (not sent to LLM)."""
        return {
            "turn_index": turn.turn_index,
            "conversation_id": turn.conversation_id,
            "bucket": turn.bucket,
        }

