"""
Hard Labeler - Discrete Label Classification

Produces discrete 0/1 labels for each turn:
- 0 = Reasoning Required
- 1 = Non-Reasoning Sufficient

Uses the underlying strategy judges (A, B, C, D) to get classifications.
"""

import logging
from typing import Dict, Any, Optional

from .base import BaseLabeler, LabelResult, LabelType

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import StrategyAJudge, StrategyBJudge, StrategyCJudge, StrategyDJudge

logger = logging.getLogger(__name__)


class HardLabeler(BaseLabeler):
    """
    Produces discrete 0/1 labels.
    
    Best for:
    - Classification tasks
    - When you need definitive labels
    - Evaluation/testing
    
    Usage:
        labeler = HardLabeler(strategy="C")
        result = labeler.label(record)
        print(result.hard_label)  # 0 or 1
    """
    
    def __init__(
        self,
        strategy: str = "A",
        use_keyvault: bool = True,
        max_concurrency: int = 10
    ):
        """
        Initialize hard labeler.
        
        Args:
            strategy: Which strategy to use (A, B, C, D)
            use_keyvault: Whether to use Azure KeyVault for credentials
            max_concurrency: Max parallel requests for batch operations
        """
        super().__init__(strategy)
        self.use_keyvault = use_keyvault
        self.max_concurrency = max_concurrency
        self._judge = None
        
        logger.info(f"Initialized HardLabeler with strategy {strategy}")
    
    @property
    def label_type(self) -> LabelType:
        return LabelType.HARD
    
    @property
    def judge(self):
        """Lazy initialization of the judge."""
        if self._judge is None:
            self._judge = self._create_judge()
        return self._judge
    
    def _create_judge(self):
        """Create the appropriate strategy judge."""
        if self.strategy == "A":
            return StrategyAJudge(use_keyvault=self.use_keyvault)
        elif self.strategy == "B":
            return StrategyBJudge(
                use_keyvault=self.use_keyvault,
                max_concurrency=self.max_concurrency
            )
        elif self.strategy == "C":
            return StrategyCJudge(
                use_keyvault=self.use_keyvault,
                max_concurrency=self.max_concurrency
            )
        elif self.strategy == "D":
            return StrategyDJudge(
                use_keyvault=self.use_keyvault,
                max_concurrency=self.max_concurrency
            )
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")
    
    def label(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a single record with a discrete label.
        
        Args:
            record: Turn data (for A, B, C) or conversation data (for D)
            
        Returns:
            LabelResult with hard_label = 0 or 1
        """
        try:
            if self.strategy == "D":
                # Strategy D needs turns array and turn index
                turns = record.get("turnsArray", [record])
                turn_index = record.get("turnIndex", 0)
                conv_id = record.get("conversationId")
                result = self.judge.classify_turn(
                    turns=turns,
                    turn_index=turn_index,
                    conversation_id=conv_id
                )
            else:
                # Strategies A, B, C use classify_from_record
                result = self.judge.classify_from_record(record)
            
            return LabelResult(
                label_type=LabelType.HARD,
                hard_label=result.label,
                confidence=result.confidence,
                strategy=self.strategy,
                soft_label=None,
                rationale=None,
                metadata={
                    "conversation_id": record.get("conversationId"),
                    "turn_index": record.get("turnIndex"),
                },
                error=result.error
            )
            
        except Exception as e:
            logger.error(f"Labeling failed: {e}")
            return LabelResult(
                label_type=LabelType.HARD,
                hard_label=-1,
                confidence=0.0,
                strategy=self.strategy,
                error=str(e)
            )
    
    async def label_async(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a single record asynchronously.
        
        Args:
            record: Turn data (for A, B, C) or conversation data (for D)
            
        Returns:
            LabelResult with hard_label = 0 or 1
        """
        try:
            if self.strategy == "D":
                turns = record.get("turnsArray", [record])
                turn_index = record.get("turnIndex", 0)
                conv_id = record.get("conversationId")
                result = await self.judge.classify_turn_async(
                    turns=turns,
                    turn_index=turn_index,
                    conversation_id=conv_id
                )
            else:
                result = await self.judge.classify_from_record_async(record)
            
            return LabelResult(
                label_type=LabelType.HARD,
                hard_label=result.label,
                confidence=result.confidence,
                strategy=self.strategy,
                soft_label=None,
                rationale=None,
                metadata={
                    "conversation_id": record.get("conversationId"),
                    "turn_index": record.get("turnIndex"),
                },
                error=result.error
            )
            
        except Exception as e:
            logger.error(f"Async labeling failed: {e}")
            return LabelResult(
                label_type=LabelType.HARD,
                hard_label=-1,
                confidence=0.0,
                strategy=self.strategy,
                error=str(e)
            )

