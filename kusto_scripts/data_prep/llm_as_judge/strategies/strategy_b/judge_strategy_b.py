"""
Strategy B: Text + Behavioral Metrics LLM Judge

Supports both sync and async API calls with tenacity retry logic.

⚠️ IMPORTANT: Strategy B uses HINDSIGHT information not available at 
deployment time. Use for labeling only, not for deployment routing.

Labels:
    0 = Reasoning Required
    1 = Non-Reasoning Sufficient

Usage:
    # Synchronous
    from strategies.strategy_b.judge_strategy_b import StrategyBJudge
    judge = StrategyBJudge()
    result = judge.classify(user_message="Fix the bug", prompt_tokens=45000, ...)
    
    # Asynchronous
    result = await judge.classify_async(user_message="Fix the bug", ...)
"""

import asyncio
import re
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log
)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.azure_foundry import (
    get_anthropic_client,
    get_async_anthropic_client,
    get_model_name,
    ASYNC_AVAILABLE
)
from config.settings import config

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

STRATEGY_NAME = "B"
STRATEGY_DESCRIPTION = "Text + Behavioral Metrics"

MAX_RETRIES = 5
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 60
DEFAULT_BATCH_CONCURRENCY = 10

SYSTEM_PROMPT = """You are an expert classifier determining whether a user request required a reasoning-capable LLM.
You have access to both the request AND what actually happened when it was processed.

CLASSIFICATION LABELS:
- 0 = REASONING REQUIRED
- 1 = NON-REASONING SUFFICIENT

BEHAVIORAL SIGNAL INTERPRETATION:

STRONG INDICATORS OF REASONING (0):
- High completion tokens (>1500) with multiple LLM calls (>2)
- Complex tool chains (file reads → analysis → edits → terminal)
- Long processing duration (>30 seconds)
- High prompt tokens (>40k) indicating accumulated context

STRONG INDICATORS OF NON-REASONING (1):
- Low completion tokens (<500) with single LLM call
- Simple or no tool usage
- Quick response (<10 seconds)

OVER-COMPLICATION CHECK:
- If behavior seems EXCESSIVE for the request, lean toward 1
- Simple question + complex behavior = model over-thought it

OUTPUT FORMAT (exactly two lines):
Line 1: Label (0 or 1)
Line 2: Confidence (decimal between 0.0 and 1.0)"""

USER_PROMPT_TEMPLATE = """USER REQUEST:
{user_message}

OBSERVED BEHAVIOR (what the LLM actually did):
- Prompt tokens used: {prompt_tokens:,}
- Completion tokens generated: {completion_tokens:,}
- Number of LLM calls: {llm_call_count}
- Tools invoked: {tool_list}
- Total tool calls: {total_tool_calls}
- Processing duration: {duration_ms:,}ms ({duration_sec:.1f}s)"""


# =============================================================================
# Retry Decorators
# =============================================================================

def _create_sync_retry():
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


def _create_async_retry():
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ClassificationResult:
    """Result of a classification."""
    label: int
    confidence: float
    strategy: str = STRATEGY_NAME
    raw_response: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "raw_response": self.raw_response,
            "error": self.error
        }


@dataclass
class BehavioralMetrics:
    """Behavioral telemetry metrics for a turn."""
    prompt_tokens: int
    completion_tokens: int
    llm_call_count: int
    tools_used: List[str]
    total_tool_calls: int
    duration_ms: int
    
    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "BehavioralMetrics":
        tools_used = record.get("toolsUsed", []) or []
        if isinstance(tools_used, str):
            tools_used = tools_used.split(", ") if tools_used else []
        
        return cls(
            prompt_tokens=record.get("promptTokens", 0) or 0,
            completion_tokens=record.get("completionTokens", 0) or 0,
            llm_call_count=record.get("llmCallCount", 1) or 1,
            tools_used=tools_used,
            total_tool_calls=record.get("totalToolCalls", len(tools_used)),
            duration_ms=record.get("durationMs", 0) or 0
        )
    
    def is_valid(self) -> bool:
        return self.prompt_tokens > 0 or self.completion_tokens > 0


# =============================================================================
# Main Judge Class
# =============================================================================

class StrategyBJudge:
    """
    LLM Judge using Strategy B: Text + Behavioral Metrics.
    Supports both synchronous and asynchronous API calls.
    """
    
    def __init__(
        self,
        use_keyvault: bool = True,
        max_tokens: int = 50,
        temperature: float = 0.0,
        max_concurrency: int = DEFAULT_BATCH_CONCURRENCY
    ):
        self.use_keyvault = use_keyvault
        self.model = get_model_name()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_concurrency = max_concurrency
        
        self._sync_client = None
        self._async_client = None
        
        logger.info(f"Initialized Strategy B Judge with model: {self.model}")
    
    @property
    def client(self):
        if self._sync_client is None:
            self._sync_client = get_anthropic_client(use_keyvault=self.use_keyvault)
        return self._sync_client
    
    @property
    def async_client(self):
        if self._async_client is None:
            if not ASYNC_AVAILABLE:
                raise ImportError("Async client not available")
            self._async_client = get_async_anthropic_client(use_keyvault=self.use_keyvault)
        return self._async_client
    
    def _build_prompt(self, user_message: str, metrics: BehavioralMetrics) -> str:
        max_len = config.labeling.max_message_length
        if len(user_message) > max_len:
            user_message = user_message[:max_len] + "... [truncated]"
        
        tool_list = ", ".join(metrics.tools_used) if metrics.tools_used else "none"
        
        return USER_PROMPT_TEMPLATE.format(
            user_message=user_message,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            llm_call_count=metrics.llm_call_count,
            tool_list=tool_list,
            total_tool_calls=metrics.total_tool_calls,
            duration_ms=metrics.duration_ms,
            duration_sec=metrics.duration_ms / 1000
        )
    
    def _parse_response(self, response_text: str) -> tuple[int, float]:
        lines = response_text.strip().split('\n')
        
        label_match = re.search(r'[01]', lines[0])
        if not label_match:
            raise ValueError(f"Could not find label in: {lines[0]}")
        label = int(label_match.group())
        
        confidence = 0.8
        confidence_line = lines[1] if len(lines) > 1 else lines[0]
        conf_match = re.search(r'0?\.[0-9]+|1\.0|1', confidence_line)
        if conf_match:
            confidence = float(conf_match.group())
            confidence = max(0.0, min(1.0, confidence))
        
        return label, confidence
    
    # =========================================================================
    # Synchronous Methods
    # =========================================================================
    
    @_create_sync_retry()
    def _call_api_sync(self, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}]
        )
        return response.content[0].text
    
    def classify(
        self,
        user_message: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        llm_call_count: int = 1,
        tools_used: Optional[List[str]] = None,
        total_tool_calls: int = 0,
        duration_ms: int = 0,
        include_raw: bool = False
    ) -> ClassificationResult:
        """Classify a user message with behavioral metrics (sync)."""
        try:
            metrics = BehavioralMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                llm_call_count=llm_call_count,
                tools_used=tools_used or [],
                total_tool_calls=total_tool_calls or len(tools_used or []),
                duration_ms=duration_ms
            )
            
            user_prompt = self._build_prompt(user_message, metrics)
            response_text = self._call_api_sync(user_prompt)
            label, confidence = self._parse_response(response_text)
            
            return ClassificationResult(
                label=label,
                confidence=confidence,
                strategy=STRATEGY_NAME,
                raw_response=response_text if include_raw else None
            )
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return ClassificationResult(label=-1, confidence=0.0, strategy=STRATEGY_NAME, error=str(e))
    
    def classify_from_record(self, record: Dict[str, Any], include_raw: bool = False) -> ClassificationResult:
        """Classify from a data record (sync)."""
        metrics = BehavioralMetrics.from_record(record)
        
        if not metrics.is_valid():
            return ClassificationResult(
                label=-1, confidence=0.0, strategy=STRATEGY_NAME,
                error="Invalid or missing behavioral metrics"
            )
        
        return self.classify(
            user_message=record.get("userMessage", ""),
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            llm_call_count=metrics.llm_call_count,
            tools_used=metrics.tools_used,
            total_tool_calls=metrics.total_tool_calls,
            duration_ms=metrics.duration_ms,
            include_raw=include_raw
        )
    
    # =========================================================================
    # Asynchronous Methods
    # =========================================================================
    
    @_create_async_retry()
    async def _call_api_async(self, user_prompt: str) -> str:
        response = await self.async_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}]
        )
        return response.content[0].text
    
    async def classify_async(
        self,
        user_message: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        llm_call_count: int = 1,
        tools_used: Optional[List[str]] = None,
        total_tool_calls: int = 0,
        duration_ms: int = 0,
        include_raw: bool = False
    ) -> ClassificationResult:
        """Classify a user message with behavioral metrics (async)."""
        try:
            metrics = BehavioralMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                llm_call_count=llm_call_count,
                tools_used=tools_used or [],
                total_tool_calls=total_tool_calls or len(tools_used or []),
                duration_ms=duration_ms
            )
            
            user_prompt = self._build_prompt(user_message, metrics)
            response_text = await self._call_api_async(user_prompt)
            label, confidence = self._parse_response(response_text)
            
            return ClassificationResult(
                label=label,
                confidence=confidence,
                strategy=STRATEGY_NAME,
                raw_response=response_text if include_raw else None
            )
        except Exception as e:
            logger.error(f"Async classification failed: {e}")
            return ClassificationResult(label=-1, confidence=0.0, strategy=STRATEGY_NAME, error=str(e))
    
    async def classify_from_record_async(self, record: Dict[str, Any], include_raw: bool = False) -> ClassificationResult:
        """Classify from a data record (async)."""
        metrics = BehavioralMetrics.from_record(record)
        
        if not metrics.is_valid():
            return ClassificationResult(
                label=-1, confidence=0.0, strategy=STRATEGY_NAME,
                error="Invalid or missing behavioral metrics"
            )
        
        return await self.classify_async(
            user_message=record.get("userMessage", ""),
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            llm_call_count=metrics.llm_call_count,
            tools_used=metrics.tools_used,
            total_tool_calls=metrics.total_tool_calls,
            duration_ms=metrics.duration_ms,
            include_raw=include_raw
        )
    
    async def classify_batch_async(
        self,
        records: List[Dict[str, Any]],
        include_raw: bool = False
    ) -> List[ClassificationResult]:
        """Classify a batch of records (async, parallel)."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def classify_with_semaphore(record: Dict, idx: int) -> tuple[int, ClassificationResult]:
            async with semaphore:
                result = await self.classify_from_record_async(record, include_raw=include_raw)
                return idx, result
        
        tasks = [classify_with_semaphore(r, i) for i, r in enumerate(records)]
        results_with_idx = await asyncio.gather(*tasks)
        results_with_idx.sort(key=lambda x: x[0])
        return [r for _, r in results_with_idx]


# =============================================================================
# Convenience Functions
# =============================================================================

def classify_with_metrics(
    user_message: str,
    prompt_tokens: int,
    completion_tokens: int,
    llm_call_count: int = 1,
    tools_used: Optional[List[str]] = None,
    duration_ms: int = 0
) -> Dict[str, Any]:
    judge = StrategyBJudge()
    result = judge.classify(
        user_message=user_message,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        llm_call_count=llm_call_count,
        tools_used=tools_used,
        duration_ms=duration_ms
    )
    return result.to_dict()
