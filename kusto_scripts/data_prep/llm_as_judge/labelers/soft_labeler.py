"""
Soft Labeler - Probability Distribution Labels

Produces soft labels (probability distributions) for each turn:
- [p_reasoning, p_non_reasoning] where p_reasoning + p_non_reasoning = 1

Benefits for SFT/KD:
- Better for Knowledge Distillation (teacher-student)
- Captures uncertainty in ambiguous cases
- Smoother gradients during training
- Preserves information about model confidence

The soft label can be derived from:
1. Confidence-based: Convert hard label + confidence to probabilities
2. Multiple runs: Average across multiple LLM judge calls
3. Ensemble: Average across multiple strategies
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Literal

from .base import BaseLabeler, LabelResult, LabelType

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import StrategyAJudge, StrategyBJudge, StrategyCJudge, StrategyDJudge

logger = logging.getLogger(__name__)


class SoftLabeler(BaseLabeler):
    """
    Produces soft probability labels instead of discrete 0/1.
    
    Best for:
    - SFT training with soft targets
    - Knowledge Distillation (teacher model)
    - Handling ambiguous cases
    - When you want to preserve uncertainty
    
    Methods for generating soft labels:
    - "confidence": Use judge's confidence score [p, 1-p]
    - "multi_run": Average N independent judge calls
    - "ensemble": Average across strategies (A, B, C, D)
    - "temperature": Apply temperature scaling to confidence
    
    Usage:
        # Confidence-based (fast, single call)
        labeler = SoftLabeler(strategy="C", method="confidence")
        result = labeler.label(record)
        print(result.soft_label)  # [0.85, 0.15]
        
        # Multi-run (slower, more robust)
        labeler = SoftLabeler(strategy="C", method="multi_run", n_runs=3)
        result = labeler.label(record)
        print(result.soft_label)  # [0.67, 0.33] (average of 3 runs)
        
        # Ensemble (slowest, most robust)
        labeler = SoftLabeler(method="ensemble", ensemble_strategies=["B", "C", "D"])
        result = labeler.label(record)
    """
    
    def __init__(
        self,
        strategy: str = "C",
        method: Literal["confidence", "multi_run", "ensemble", "temperature"] = "confidence",
        use_keyvault: bool = True,
        max_concurrency: int = 10,
        n_runs: int = 3,
        temperature: float = 1.0,
        ensemble_strategies: Optional[List[str]] = None
    ):
        """
        Initialize soft labeler.
        
        Args:
            strategy: Primary strategy (A, B, C, D) - used for non-ensemble methods
            method: How to generate soft labels
                - "confidence": Convert confidence to probability
                - "multi_run": Average N independent calls
                - "ensemble": Average across strategies
                - "temperature": Apply temperature scaling
            use_keyvault: Whether to use Azure KeyVault for credentials
            max_concurrency: Max parallel requests
            n_runs: Number of runs for multi_run method
            temperature: Temperature for scaling (>1 = softer, <1 = sharper)
            ensemble_strategies: Strategies to use for ensemble method
        """
        super().__init__(strategy)
        self.method = method
        self.use_keyvault = use_keyvault
        self.max_concurrency = max_concurrency
        self.n_runs = n_runs
        self.temperature = temperature
        self.ensemble_strategies = ensemble_strategies or ["B", "C", "D"]
        
        self._judges: Dict[str, Any] = {}
        
        logger.info(
            f"Initialized SoftLabeler with strategy={strategy}, method={method}, "
            f"n_runs={n_runs}, temperature={temperature}"
        )
    
    @property
    def label_type(self) -> LabelType:
        return LabelType.SOFT
    
    def _get_judge(self, strategy: str):
        """Get or create a judge for the given strategy."""
        if strategy not in self._judges:
            if strategy == "A":
                self._judges[strategy] = StrategyAJudge(use_keyvault=self.use_keyvault)
            elif strategy == "B":
                self._judges[strategy] = StrategyBJudge(
                    use_keyvault=self.use_keyvault,
                    max_concurrency=self.max_concurrency
                )
            elif strategy == "C":
                self._judges[strategy] = StrategyCJudge(
                    use_keyvault=self.use_keyvault,
                    max_concurrency=self.max_concurrency
                )
            elif strategy == "D":
                self._judges[strategy] = StrategyDJudge(
                    use_keyvault=self.use_keyvault,
                    max_concurrency=self.max_concurrency
                )
        return self._judges[strategy]
    
    def _confidence_to_soft_label(
        self,
        hard_label: int,
        confidence: float,
        temperature: float = 1.0
    ) -> List[float]:
        """
        Convert hard label + confidence to soft probability distribution.
        
        Args:
            hard_label: 0 (reasoning) or 1 (non-reasoning)
            confidence: Judge's confidence (0.0 to 1.0)
            temperature: Scaling factor (>1 = softer, <1 = sharper)
            
        Returns:
            [p_reasoning, p_non_reasoning] summing to 1.0
        """
        # Clamp confidence
        confidence = max(0.5, min(1.0, confidence))
        
        # Apply temperature scaling
        if temperature != 1.0:
            # Use logit scaling
            import math
            logit = math.log(confidence / (1 - confidence + 1e-10))
            logit /= temperature
            confidence = 1 / (1 + math.exp(-logit))
        
        if hard_label == 0:  # Reasoning required
            return [confidence, 1 - confidence]
        else:  # Non-reasoning sufficient
            return [1 - confidence, confidence]
    
    def _classify_single(self, record: Dict[str, Any], strategy: str) -> tuple[int, float]:
        """Run a single classification and return (label, confidence)."""
        judge = self._get_judge(strategy)
        
        if strategy == "D":
            turns = record.get("turnsArray", [record])
            turn_index = record.get("turnIndex", 0)
            result = judge.classify_turn(turns=turns, turn_index=turn_index)
        else:
            result = judge.classify_from_record(record)
        
        return result.label, result.confidence
    
    async def _classify_single_async(
        self,
        record: Dict[str, Any],
        strategy: str
    ) -> tuple[int, float]:
        """Run a single async classification."""
        judge = self._get_judge(strategy)
        
        if strategy == "D":
            turns = record.get("turnsArray", [record])
            turn_index = record.get("turnIndex", 0)
            result = await judge.classify_turn_async(turns=turns, turn_index=turn_index)
        else:
            result = await judge.classify_from_record_async(record)
        
        return result.label, result.confidence
    
    def _aggregate_soft_labels(self, soft_labels: List[List[float]]) -> List[float]:
        """Average multiple soft labels."""
        n = len(soft_labels)
        if n == 0:
            return [0.5, 0.5]
        
        p_reasoning = sum(sl[0] for sl in soft_labels) / n
        p_non_reasoning = sum(sl[1] for sl in soft_labels) / n
        
        # Normalize to ensure sum = 1
        total = p_reasoning + p_non_reasoning
        return [p_reasoning / total, p_non_reasoning / total]
    
    def label(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a record with soft probabilities (sync).
        
        Returns:
            LabelResult with soft_label = [p_reasoning, p_non_reasoning]
        """
        try:
            if self.method == "confidence":
                # Single call, use confidence as probability
                label, confidence = self._classify_single(record, self.strategy)
                soft_label = self._confidence_to_soft_label(
                    label, confidence, self.temperature
                )
                
            elif self.method == "temperature":
                # Same as confidence but with temperature scaling
                label, confidence = self._classify_single(record, self.strategy)
                soft_label = self._confidence_to_soft_label(
                    label, confidence, self.temperature
                )
                
            elif self.method == "multi_run":
                # Multiple independent calls, average results
                soft_labels = []
                for _ in range(self.n_runs):
                    label, confidence = self._classify_single(record, self.strategy)
                    sl = self._confidence_to_soft_label(label, confidence)
                    soft_labels.append(sl)
                soft_label = self._aggregate_soft_labels(soft_labels)
                
            elif self.method == "ensemble":
                # Multiple strategies, average results
                soft_labels = []
                for strategy in self.ensemble_strategies:
                    try:
                        label, confidence = self._classify_single(record, strategy)
                        sl = self._confidence_to_soft_label(label, confidence)
                        soft_labels.append(sl)
                    except Exception as e:
                        logger.warning(f"Strategy {strategy} failed: {e}")
                soft_label = self._aggregate_soft_labels(soft_labels)
                
            else:
                raise ValueError(f"Unknown method: {self.method}")
            
            # Derive hard label from soft label
            hard_label = 0 if soft_label[0] > soft_label[1] else 1
            confidence = max(soft_label)
            
            return LabelResult(
                label_type=LabelType.SOFT,
                hard_label=hard_label,
                confidence=confidence,
                strategy=self.strategy if self.method != "ensemble" else "ensemble",
                soft_label=soft_label,
                rationale=None,
                metadata={
                    "method": self.method,
                    "temperature": self.temperature,
                    "n_runs": self.n_runs if self.method == "multi_run" else None,
                    "ensemble_strategies": self.ensemble_strategies if self.method == "ensemble" else None,
                    "conversation_id": record.get("conversationId"),
                    "turn_index": record.get("turnIndex"),
                }
            )
            
        except Exception as e:
            logger.error(f"Soft labeling failed: {e}")
            return LabelResult(
                label_type=LabelType.SOFT,
                hard_label=-1,
                confidence=0.0,
                strategy=self.strategy,
                soft_label=[0.5, 0.5],
                error=str(e)
            )
    
    async def label_async(self, record: Dict[str, Any]) -> LabelResult:
        """
        Label a record with soft probabilities (async).
        
        More efficient for multi_run and ensemble methods.
        """
        try:
            if self.method == "confidence" or self.method == "temperature":
                # Single call
                label, confidence = await self._classify_single_async(record, self.strategy)
                soft_label = self._confidence_to_soft_label(
                    label, confidence, self.temperature
                )
                
            elif self.method == "multi_run":
                # Multiple parallel calls
                tasks = [
                    self._classify_single_async(record, self.strategy)
                    for _ in range(self.n_runs)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                soft_labels = []
                for result in results:
                    if isinstance(result, Exception):
                        logger.warning(f"Run failed: {result}")
                        continue
                    label, confidence = result
                    sl = self._confidence_to_soft_label(label, confidence)
                    soft_labels.append(sl)
                
                soft_label = self._aggregate_soft_labels(soft_labels)
                
            elif self.method == "ensemble":
                # Multiple strategies in parallel
                tasks = [
                    self._classify_single_async(record, strategy)
                    for strategy in self.ensemble_strategies
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                soft_labels = []
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.warning(f"Strategy {self.ensemble_strategies[i]} failed: {result}")
                        continue
                    label, confidence = result
                    sl = self._confidence_to_soft_label(label, confidence)
                    soft_labels.append(sl)
                
                soft_label = self._aggregate_soft_labels(soft_labels)
                
            else:
                raise ValueError(f"Unknown method: {self.method}")
            
            hard_label = 0 if soft_label[0] > soft_label[1] else 1
            confidence = max(soft_label)
            
            return LabelResult(
                label_type=LabelType.SOFT,
                hard_label=hard_label,
                confidence=confidence,
                strategy=self.strategy if self.method != "ensemble" else "ensemble",
                soft_label=soft_label,
                rationale=None,
                metadata={
                    "method": self.method,
                    "temperature": self.temperature,
                    "n_runs": self.n_runs if self.method == "multi_run" else None,
                    "ensemble_strategies": self.ensemble_strategies if self.method == "ensemble" else None,
                    "conversation_id": record.get("conversationId"),
                    "turn_index": record.get("turnIndex"),
                }
            )
            
        except Exception as e:
            logger.error(f"Async soft labeling failed: {e}")
            return LabelResult(
                label_type=LabelType.SOFT,
                hard_label=-1,
                confidence=0.0,
                strategy=self.strategy,
                soft_label=[0.5, 0.5],
                error=str(e)
            )


# =============================================================================
# Convenience Functions
# =============================================================================

def get_soft_label(
    record: Dict[str, Any],
    strategy: str = "C",
    temperature: float = 1.0
) -> Dict[str, Any]:
    """
    Quick function to get soft label for a record.
    
    Args:
        record: Turn data
        strategy: Which strategy to use
        temperature: Softening factor
        
    Returns:
        Dict with soft_label and metadata
    """
    labeler = SoftLabeler(strategy=strategy, temperature=temperature)
    result = labeler.label(record)
    return result.to_dict()


async def get_soft_label_async(
    record: Dict[str, Any],
    strategy: str = "C",
    temperature: float = 1.0
) -> Dict[str, Any]:
    """Async version of get_soft_label."""
    labeler = SoftLabeler(strategy=strategy, temperature=temperature)
    result = await labeler.label_async(record)
    return result.to_dict()

