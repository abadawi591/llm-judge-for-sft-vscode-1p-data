"""
Ensemble Voting for LLM-as-Judge Classification

Supports both sync and async API calls with tenacity retry logic.

Voting Strategies:
1. Strategy Voting: Combine A, B, C strategy outputs
2. Model Voting: Same strategy, different LLM models
3. Self-Consistency: Same model, multiple runs with temperature > 0
4. Cascade: Escalate from cheap to expensive based on confidence

Labels:
    0 = Reasoning Required
    1 = Non-Reasoning Sufficient

Usage:
    # Synchronous
    judge = EnsembleJudge(strategies=["A", "B", "C"])
    result = judge.classify(record)
    
    # Asynchronous (parallel across strategies)
    result = await judge.classify_async(record)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.strategy_a.judge_strategy_a import StrategyAJudge, ClassificationResult
from strategies.strategy_b.judge_strategy_b import StrategyBJudge
from strategies.strategy_c.judge_strategy_c import StrategyCJudge
from config.settings import config

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class VotingMethod(Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    CONFIDENCE = "confidence"
    UNANIMOUS = "unanimous"


DEFAULT_STRATEGY_WEIGHTS = {
    "A": 0.20,
    "B": 0.30,
    "C": 0.50
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EnsembleResult:
    """Result from ensemble voting."""
    label: int
    confidence: float
    agreement: bool
    agreement_ratio: float
    individual_results: Dict[str, ClassificationResult] = field(default_factory=dict)
    voting_method: str = "weighted"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "agreement": self.agreement,
            "agreement_ratio": self.agreement_ratio,
            "voting_method": self.voting_method,
            "individual_results": {
                k: v.to_dict() for k, v in self.individual_results.items()
            }
        }


# =============================================================================
# Voting Functions
# =============================================================================

def majority_vote(results: List[ClassificationResult]) -> tuple[int, float]:
    """Simple majority voting."""
    if not results:
        raise ValueError("Cannot vote with empty results")
    
    labels = [r.label for r in results if r.label >= 0]
    if not labels:
        return -1, 0.0
    
    reasoning_votes = labels.count(0)
    non_reasoning_votes = labels.count(1)
    
    if reasoning_votes > non_reasoning_votes:
        return 0, reasoning_votes / len(labels)
    elif non_reasoning_votes > reasoning_votes:
        return 1, non_reasoning_votes / len(labels)
    else:
        return 0, 0.5  # Tie: default to reasoning


def weighted_vote(results: List[ClassificationResult], weights: Dict[str, float]) -> tuple[int, float]:
    """Weighted voting based on strategy weights."""
    if not results:
        raise ValueError("Cannot vote with empty results")
    
    reasoning_score = 0.0
    non_reasoning_score = 0.0
    total_weight = 0.0
    
    for result in results:
        if result.label < 0:
            continue
        
        weight = weights.get(result.strategy, 0.33)
        weighted_conf = result.confidence * weight
        
        if result.label == 0:
            reasoning_score += weighted_conf
        else:
            non_reasoning_score += weighted_conf
        
        total_weight += weight
    
    if total_weight == 0:
        return -1, 0.0
    
    reasoning_score /= total_weight
    non_reasoning_score /= total_weight
    
    if reasoning_score >= non_reasoning_score:
        return 0, reasoning_score / (reasoning_score + non_reasoning_score + 1e-10)
    else:
        return 1, non_reasoning_score / (reasoning_score + non_reasoning_score + 1e-10)


def confidence_vote(results: List[ClassificationResult]) -> tuple[int, float]:
    """Vote weighted by each judge's confidence."""
    if not results:
        raise ValueError("Cannot vote with empty results")
    
    reasoning_score = sum(r.confidence for r in results if r.label == 0)
    non_reasoning_score = sum(r.confidence for r in results if r.label == 1)
    
    total = reasoning_score + non_reasoning_score
    if total == 0:
        return -1, 0.0
    
    if reasoning_score >= non_reasoning_score:
        return 0, reasoning_score / total
    else:
        return 1, non_reasoning_score / total


# =============================================================================
# Ensemble Judge Class
# =============================================================================

class EnsembleJudge:
    """
    Ensemble judge that combines multiple strategy classifications.
    Supports both sync and async operations.
    """
    
    def __init__(
        self,
        strategies: List[str] = None,
        weights: Dict[str, float] = None,
        voting_method: VotingMethod = VotingMethod.WEIGHTED,
        use_keyvault: bool = True
    ):
        self.strategies = strategies or ["A", "B", "C"]
        self.weights = weights or DEFAULT_STRATEGY_WEIGHTS
        self.voting_method = voting_method
        self.use_keyvault = use_keyvault
        
        # Initialize judges
        self.judges = {}
        if "A" in self.strategies:
            self.judges["A"] = StrategyAJudge(use_keyvault=use_keyvault)
        if "B" in self.strategies:
            self.judges["B"] = StrategyBJudge(use_keyvault=use_keyvault)
        if "C" in self.strategies:
            self.judges["C"] = StrategyCJudge(use_keyvault=use_keyvault)
        
        logger.info(f"Initialized EnsembleJudge with strategies: {self.strategies}")
    
    def _compute_ensemble(self, results: Dict[str, ClassificationResult]) -> EnsembleResult:
        """Compute ensemble result from individual results."""
        valid_results = [r for r in results.values() if r.label >= 0]
        
        if not valid_results:
            return EnsembleResult(
                label=-1, confidence=0.0, agreement=False, agreement_ratio=0.0,
                individual_results=results, voting_method=self.voting_method.value
            )
        
        labels = [r.label for r in valid_results]
        agreement = len(set(labels)) == 1
        most_common = max(set(labels), key=labels.count)
        agreement_ratio = labels.count(most_common) / len(labels)
        
        if self.voting_method == VotingMethod.MAJORITY:
            label, confidence = majority_vote(valid_results)
        elif self.voting_method == VotingMethod.WEIGHTED:
            label, confidence = weighted_vote(valid_results, self.weights)
        elif self.voting_method == VotingMethod.CONFIDENCE:
            label, confidence = confidence_vote(valid_results)
        else:
            if agreement:
                label = labels[0]
                confidence = sum(r.confidence for r in valid_results) / len(valid_results)
            else:
                label = -1
                confidence = 0.0
        
        return EnsembleResult(
            label=label,
            confidence=confidence,
            agreement=agreement,
            agreement_ratio=agreement_ratio,
            individual_results=results,
            voting_method=self.voting_method.value
        )
    
    # =========================================================================
    # Synchronous Methods
    # =========================================================================
    
    def classify(self, record: Dict[str, Any], include_raw: bool = False) -> EnsembleResult:
        """Classify a record using all strategies and vote (sync)."""
        results = {}
        
        for strategy in self.strategies:
            try:
                if strategy == "A":
                    results["A"] = self.judges["A"].classify(
                        record.get("userMessage", ""), include_raw=include_raw
                    )
                elif strategy == "B":
                    results["B"] = self.judges["B"].classify_from_record(
                        record, include_raw=include_raw
                    )
                elif strategy == "C":
                    turns = record.get("turnsArray", [])
                    turn_index = record.get("turnIndex", len(turns) - 1)
                    results["C"] = self.judges["C"].classify_turn(
                        turns=turns, turn_index=turn_index,
                        conversation_id=record.get("conversationId"),
                        include_raw=include_raw
                    )
            except Exception as e:
                logger.error(f"Strategy {strategy} failed: {e}")
                results[strategy] = ClassificationResult(
                    label=-1, confidence=0.0, strategy=strategy, error=str(e)
                )
        
        return self._compute_ensemble(results)
    
    # =========================================================================
    # Asynchronous Methods
    # =========================================================================
    
    async def classify_async(self, record: Dict[str, Any], include_raw: bool = False) -> EnsembleResult:
        """Classify a record using all strategies in parallel (async)."""
        
        async def run_strategy_a():
            return "A", await self.judges["A"].classify_async(
                record.get("userMessage", ""), include_raw=include_raw
            )
        
        async def run_strategy_b():
            return "B", await self.judges["B"].classify_from_record_async(
                record, include_raw=include_raw
            )
        
        async def run_strategy_c():
            turns = record.get("turnsArray", [])
            turn_index = record.get("turnIndex", len(turns) - 1)
            return "C", await self.judges["C"].classify_turn_async(
                turns=turns, turn_index=turn_index,
                conversation_id=record.get("conversationId"),
                include_raw=include_raw
            )
        
        # Build tasks for requested strategies
        tasks = []
        if "A" in self.strategies:
            tasks.append(run_strategy_a())
        if "B" in self.strategies:
            tasks.append(run_strategy_b())
        if "C" in self.strategies:
            tasks.append(run_strategy_c())
        
        # Run all strategies in parallel
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = {}
        for item in results_list:
            if isinstance(item, Exception):
                logger.error(f"Strategy failed: {item}")
                continue
            strategy, result = item
            results[strategy] = result
        
        return self._compute_ensemble(results)
    
    async def classify_batch_async(
        self,
        records: List[Dict[str, Any]],
        include_raw: bool = False,
        max_concurrency: int = 10
    ) -> List[EnsembleResult]:
        """Classify a batch of records (async, parallel)."""
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def classify_with_semaphore(record: Dict, idx: int) -> tuple[int, EnsembleResult]:
            async with semaphore:
                result = await self.classify_async(record, include_raw=include_raw)
                return idx, result
        
        tasks = [classify_with_semaphore(r, i) for i, r in enumerate(records)]
        results_with_idx = await asyncio.gather(*tasks)
        results_with_idx.sort(key=lambda x: x[0])
        return [r for _, r in results_with_idx]


# =============================================================================
# Cascade Judge Class
# =============================================================================

class CascadeJudge:
    """
    Cascade judge that escalates from cheap to expensive strategies
    based on confidence thresholds. Supports sync and async.
    """
    
    def __init__(
        self,
        step1_threshold: float = 0.90,
        step2_threshold: float = 0.85,
        use_keyvault: bool = True
    ):
        self.step1_threshold = step1_threshold
        self.step2_threshold = step2_threshold
        
        self.judge_a = StrategyAJudge(use_keyvault=use_keyvault)
        self.judge_c = StrategyCJudge(use_keyvault=use_keyvault)
        self.ensemble = EnsembleJudge(strategies=["A", "B", "C"], use_keyvault=use_keyvault)
        
        logger.info("Initialized CascadeJudge")
    
    def classify(self, record: Dict[str, Any], include_raw: bool = False) -> Dict[str, Any]:
        """Classify with cascade escalation (sync)."""
        # Step 1: Try Strategy A
        result_a = self.judge_a.classify(record.get("userMessage", ""), include_raw=include_raw)
        
        if result_a.confidence >= self.step1_threshold:
            return {
                "label": result_a.label,
                "confidence": result_a.confidence,
                "strategy": "A",
                "escalation_level": 1,
                "steps_taken": ["A"]
            }
        
        # Step 2: Try Strategy C
        turns = record.get("turnsArray", [])
        turn_index = record.get("turnIndex", len(turns) - 1)
        
        result_c = self.judge_c.classify_turn(
            turns=turns, turn_index=turn_index,
            conversation_id=record.get("conversationId"),
            include_raw=include_raw
        )
        
        if result_c.confidence >= self.step2_threshold:
            return {
                "label": result_c.label,
                "confidence": result_c.confidence,
                "strategy": "C",
                "escalation_level": 2,
                "steps_taken": ["A", "C"]
            }
        
        # Step 3: Full voting
        ensemble_result = self.ensemble.classify(record, include_raw=include_raw)
        
        return {
            "label": ensemble_result.label,
            "confidence": ensemble_result.confidence,
            "strategy": "ensemble",
            "escalation_level": 3,
            "steps_taken": ["A", "C", "A+B+C"],
            "agreement": ensemble_result.agreement,
            "agreement_ratio": ensemble_result.agreement_ratio
        }
    
    async def classify_async(self, record: Dict[str, Any], include_raw: bool = False) -> Dict[str, Any]:
        """Classify with cascade escalation (async)."""
        # Step 1: Try Strategy A
        result_a = await self.judge_a.classify_async(record.get("userMessage", ""), include_raw=include_raw)
        
        if result_a.confidence >= self.step1_threshold:
            return {
                "label": result_a.label,
                "confidence": result_a.confidence,
                "strategy": "A",
                "escalation_level": 1,
                "steps_taken": ["A"]
            }
        
        # Step 2: Try Strategy C
        turns = record.get("turnsArray", [])
        turn_index = record.get("turnIndex", len(turns) - 1)
        
        result_c = await self.judge_c.classify_turn_async(
            turns=turns, turn_index=turn_index,
            conversation_id=record.get("conversationId"),
            include_raw=include_raw
        )
        
        if result_c.confidence >= self.step2_threshold:
            return {
                "label": result_c.label,
                "confidence": result_c.confidence,
                "strategy": "C",
                "escalation_level": 2,
                "steps_taken": ["A", "C"]
            }
        
        # Step 3: Full voting (parallel)
        ensemble_result = await self.ensemble.classify_async(record, include_raw=include_raw)
        
        return {
            "label": ensemble_result.label,
            "confidence": ensemble_result.confidence,
            "strategy": "ensemble",
            "escalation_level": 3,
            "steps_taken": ["A", "C", "A+B+C"],
            "agreement": ensemble_result.agreement,
            "agreement_ratio": ensemble_result.agreement_ratio
        }
