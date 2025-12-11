"""
Base Labeler Interface

Defines the contract for all labelers (hard and soft).
Follows the Strategy pattern for flexibility.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class LabelType(Enum):
    """Type of label output."""
    HARD = "hard"  # Discrete: 0 or 1
    SOFT = "soft"  # Probability: [p_reasoning, p_non_reasoning]


@dataclass
class LabelResult:
    """
    Result from any labeler (hard or soft).
    
    Attributes:
        label_type: Whether this is a hard or soft label
        hard_label: Discrete label (0=reasoning, 1=non-reasoning) - always present
        soft_label: Probability distribution [p_reasoning, p_non_reasoning] - for soft labels
        confidence: Confidence in the label (from LLM judge)
        strategy: Which strategy was used (A, B, C, D)
        rationale: Optional explanation from the judge
        metadata: Additional info (turn_index, conversation_id, etc.)
    """
    label_type: LabelType
    hard_label: int  # 0 or 1, always provided
    confidence: float
    strategy: str
    soft_label: Optional[List[float]] = None  # [p_reasoning, p_non_reasoning]
    rationale: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    @property
    def p_reasoning(self) -> float:
        """Probability that reasoning is required (label=0)."""
        if self.soft_label:
            return self.soft_label[0]
        # For hard labels, use confidence to estimate
        return self.confidence if self.hard_label == 0 else 1 - self.confidence
    
    @property
    def p_non_reasoning(self) -> float:
        """Probability that non-reasoning is sufficient (label=1)."""
        if self.soft_label:
            return self.soft_label[1]
        return self.confidence if self.hard_label == 1 else 1 - self.confidence
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "label_type": self.label_type.value,
            "hard_label": self.hard_label,
            "confidence": self.confidence,
            "strategy": self.strategy,
        }
        if self.soft_label:
            result["soft_label"] = self.soft_label
            result["p_reasoning"] = self.p_reasoning
            result["p_non_reasoning"] = self.p_non_reasoning
        if self.rationale:
            result["rationale"] = self.rationale
        if self.metadata:
            result["metadata"] = self.metadata
        if self.error:
            result["error"] = self.error
        return result
    
    def to_sft_format(self) -> Dict[str, Any]:
        """
        Convert to format suitable for SFT training.
        
        For soft labels, returns distribution.
        For hard labels, returns one-hot encoding.
        """
        if self.soft_label:
            return {
                "label_distribution": self.soft_label,
                "temperature": 1.0,  # Can be adjusted for sharpening
            }
        else:
            # One-hot encoding for hard labels
            return {
                "label_distribution": [1.0, 0.0] if self.hard_label == 0 else [0.0, 1.0],
                "temperature": 0.0,  # Sharp (one-hot)
            }


class BaseLabeler(ABC):
    """
    Abstract base class for all labelers.
    
    Labelers classify turns/requests as:
    - 0 = Reasoning Required
    - 1 = Non-Reasoning Sufficient
    
    Subclasses implement specific labeling logic:
    - HardLabeler: Returns discrete 0/1 labels
    - SoftLabeler: Returns probability distributions
    """
    
    def __init__(self, strategy: str = "A"):
        """
        Initialize labeler with a strategy.
        
        Args:
            strategy: Which strategy to use (A, B, C, D)
        """
        self.strategy = strategy.upper()
        self._validate_strategy()
    
    def _validate_strategy(self):
        """Validate the strategy is supported."""
        valid = {"A", "B", "C", "D"}
        if self.strategy not in valid:
            raise ValueError(f"Strategy must be one of {valid}, got {self.strategy}")
    
    @property
    @abstractmethod
    def label_type(self) -> LabelType:
        """Return the type of labels this labeler produces."""
        pass
    
    @abstractmethod
    def label(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a single record.
        
        Args:
            record: Turn or conversation data
            
        Returns:
            LabelResult with label and metadata
        """
        pass
    
    @abstractmethod
    async def label_async(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a single record asynchronously.
        
        Args:
            record: Turn or conversation data
            
        Returns:
            LabelResult with label and metadata
        """
        pass
    
    async def label_batch_async(
        self,
        records: List[Dict[str, Any]],
        max_concurrency: int = 10
    ) -> List[LabelResult]:
        """
        Label a batch of records in parallel.
        
        Args:
            records: List of turn/conversation data
            max_concurrency: Maximum parallel requests
            
        Returns:
            List of LabelResults in same order as input
        """
        import asyncio
        
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def label_with_semaphore(record: Dict, idx: int) -> tuple[int, LabelResult]:
            async with semaphore:
                result = await self.label_async(record)
                return idx, result
        
        tasks = [label_with_semaphore(r, i) for i, r in enumerate(records)]
        results_with_idx = await asyncio.gather(*tasks)
        results_with_idx.sort(key=lambda x: x[0])
        return [r for _, r in results_with_idx]
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(strategy={self.strategy})"

