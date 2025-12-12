"""
Base Strategy Module
====================

Abstract base class for labeling strategies.

A labeling strategy defines:
    1. What input the LLM sees when classifying
    2. How to extract the text to classify from a turn record

Different strategies may produce different labels because they
present different information to the LLM. This allows experimentation
with context, metadata, and other factors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..io.schemas import TurnRecord


@dataclass
class StrategyResult:
    """
    Result of applying a strategy to a turn.
    
    Attributes:
        text_to_classify: The text that will be sent to the LLM
        strategy_name: Name of the strategy that produced this
        turn_record: The original turn record
        metadata: Any additional metadata from the strategy
    """
    text_to_classify: str
    strategy_name: str
    turn_record: TurnRecord
    metadata: Optional[dict] = None


class LabelingStrategy(ABC):
    """
    Abstract base class for labeling strategies.
    
    A strategy defines what input the LLM sees when classifying a turn.
    Different strategies may produce different labels because they
    present different context to the model.
    
    Subclasses must implement:
        - name: Human-readable strategy name
        - description: Explanation of what the strategy does
        - extract_text: Convert a TurnRecord to classification input
    
    Example:
        >>> class MyStrategy(LabelingStrategy):
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_strategy"
        ...     
        ...     def extract_text(self, turn: TurnRecord) -> str:
        ...         return turn.user_message
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name (e.g., 'user_message_only')."""
        pass
    
    @property
    def description(self) -> str:
        """Description of what this strategy does."""
        return "Base labeling strategy"
    
    @abstractmethod
    def extract_text(self, turn: TurnRecord) -> str:
        """
        Extract the text to classify from a turn record.
        
        This is the core method that defines what the LLM sees.
        
        Args:
            turn: The turn record to process
        
        Returns:
            The text string to send to the classifier
        """
        pass
    
    def apply(self, turn: TurnRecord) -> StrategyResult:
        """
        Apply the strategy to a turn record.
        
        Args:
            turn: The turn record to process
        
        Returns:
            StrategyResult with the text to classify
        """
        text = self.extract_text(turn)
        
        return StrategyResult(
            text_to_classify=text,
            strategy_name=self.name,
            turn_record=turn,
            metadata=self._get_metadata(turn),
        )
    
    def _get_metadata(self, turn: TurnRecord) -> Optional[dict]:
        """
        Extract any strategy-specific metadata.
        
        Override in subclasses to include additional info.
        
        Args:
            turn: The turn record
        
        Returns:
            Optional metadata dictionary
        """
        return None

