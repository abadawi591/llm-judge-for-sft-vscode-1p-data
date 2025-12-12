"""
Strategy A: Text Only (Baseline) LLM Judge

This module implements the simplest labeling strategy where the LLM judge
sees ONLY the current user message—no conversation history, no behavioral
metrics. Supports both sync and async API calls with tenacity retry logic.

Strategy A is ideal for:
- Deployment-time routing (matches inference input)
- Baseline comparison
- First-turn classification
- Cost-sensitive labeling

Labels:
    0 = Reasoning Required
    1 = Non-Reasoning Sufficient

Usage:
    # Synchronous
    from strategies.strategy_a.judge_strategy_a import StrategyAJudge
    judge = StrategyAJudge()
    result = judge.classify("Fix the authentication bug")
    
    # Asynchronous
    result = await judge.classify_async("Fix the authentication bug")
    
    # Batch async (parallel processing)
    results = await judge.classify_batch_async(messages)

Azure Foundry Configuration:
    - Endpoint: https://pagolnar-5985-resource.services.ai.azure.com/anthropic/
    - Model: claude-sonnet-4-5
    - Key Vault: claude-keyvault / claude-sonnet-4-5-azurefoundary
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
    retry_if_exception_type,
    before_sleep_log
)

# Add parent directory to path for imports
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

STRATEGY_NAME = "A"
STRATEGY_DESCRIPTION = "Text Only (Baseline)"

# Retry configuration
MAX_RETRIES = 5
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 60

# Batch processing
DEFAULT_BATCH_CONCURRENCY = 10  # Max concurrent async requests

SYSTEM_PROMPT = """You are an expert classifier determining whether a user request requires a reasoning-capable LLM.

CLASSIFICATION LABELS:
- 0 = REASONING REQUIRED: Complex multi-step problems, debugging, refactoring, architectural decisions, ambiguous requests, code generation/analysis, "why" questions
- 1 = NON-REASONING SUFFICIENT: Simple direct questions, straightforward lookups, single obvious edits, yes/no questions, simple formatting

OUTPUT FORMAT (exactly two lines):
Line 1: Label (0 or 1)
Line 2: Confidence (decimal between 0.0 and 1.0)

Example:
0
0.85"""

USER_PROMPT_TEMPLATE = """USER REQUEST:
{user_message}"""


# =============================================================================
# Retry Decorators
# =============================================================================

def _create_sync_retry():
    """Create sync retry decorator with tenacity."""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=MIN_WAIT_SECONDS, max=MAX_WAIT_SECONDS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


def _create_async_retry():
    """Create async retry decorator with tenacity."""
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
    label: int  # 0 = reasoning, 1 = non-reasoning
    confidence: float  # 0.0 to 1.0
    strategy: str = STRATEGY_NAME
    raw_response: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "label": self.label,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "raw_response": self.raw_response,
            "error": self.error
        }


# =============================================================================
# Main Judge Class
# =============================================================================

class StrategyAJudge:
    """
    LLM Judge using Strategy A: Text Only.
    
    Supports both synchronous and asynchronous API calls with tenacity
    retry logic for handling transient failures.
    
    Attributes:
        client: Synchronous Anthropic Foundry client
        async_client: Asynchronous Anthropic Foundry client (lazy loaded)
        model: Model name (claude-sonnet-4-5)
        max_tokens: Maximum tokens for response
        temperature: Sampling temperature (0.0 for deterministic)
    """
    
    def __init__(
        self,
        use_keyvault: bool = True,
        max_tokens: int = 50,
        temperature: float = 0.0,
        max_concurrency: int = DEFAULT_BATCH_CONCURRENCY
    ):
        """
        Initialize the Strategy A judge.
        
        Args:
            use_keyvault: If True, retrieve API key from Azure Key Vault
            max_tokens: Maximum tokens for LLM response
            temperature: Sampling temperature (0.0 = deterministic)
            max_concurrency: Maximum concurrent async requests
        """
        self.use_keyvault = use_keyvault
        self.model = get_model_name()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_concurrency = max_concurrency
        
        # Lazy load clients
        self._sync_client = None
        self._async_client = None
        
        logger.info(f"Initialized Strategy A Judge with model: {self.model}")
    
    @property
    def client(self):
        """Lazy load synchronous client."""
        if self._sync_client is None:
            self._sync_client = get_anthropic_client(use_keyvault=self.use_keyvault)
        return self._sync_client
    
    @property
    def async_client(self):
        """Lazy load asynchronous client."""
        if self._async_client is None:
            if not ASYNC_AVAILABLE:
                raise ImportError("Async client not available")
            self._async_client = get_async_anthropic_client(use_keyvault=self.use_keyvault)
        return self._async_client
    
    def _build_prompt(self, user_message: str) -> str:
        """Build the user prompt from the message."""
        max_len = config.labeling.max_message_length
        if len(user_message) > max_len:
            user_message = user_message[:max_len] + "... [truncated]"
        
        return USER_PROMPT_TEMPLATE.format(user_message=user_message)
    
    def _parse_response(self, response_text: str) -> tuple[int, float]:
        """Parse the LLM response to extract label and confidence."""
        lines = response_text.strip().split('\n')
        
        # Extract label from first line
        label_match = re.search(r'[01]', lines[0])
        if not label_match:
            raise ValueError(f"Could not find label (0 or 1) in: {lines[0]}")
        label = int(label_match.group())
        
        # Extract confidence from second line
        confidence = 0.8  # Default
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
        """Make synchronous API call with retry logic."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}
            ]
        )
        return response.content[0].text
    
    def classify(
        self,
        user_message: str,
        include_raw: bool = False
    ) -> ClassificationResult:
        """
        Classify a single user message (synchronous).
        
        Args:
            user_message: The user's request to classify
            include_raw: If True, include raw LLM response in result
            
        Returns:
            ClassificationResult with label, confidence, and metadata
        """
        try:
            user_prompt = self._build_prompt(user_message)
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
            return ClassificationResult(
                label=-1,
                confidence=0.0,
                strategy=STRATEGY_NAME,
                error=str(e)
            )
    
    def classify_batch(
        self,
        messages: List[str],
        include_raw: bool = False
    ) -> List[ClassificationResult]:
        """
        Classify a batch of messages (synchronous, sequential).
        
        For parallel processing, use classify_batch_async.
        """
        results = []
        for i, message in enumerate(messages):
            if i > 0 and i % 10 == 0:
                logger.info(f"Processed {i}/{len(messages)} messages")
            result = self.classify(message, include_raw=include_raw)
            results.append(result)
        return results
    
    # =========================================================================
    # Asynchronous Methods
    # =========================================================================
    
    @_create_async_retry()
    async def _call_api_async(self, user_prompt: str) -> str:
        """Make asynchronous API call with retry logic."""
        response = await self.async_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}
            ]
        )
        return response.content[0].text
    
    async def classify_async(
        self,
        user_message: str,
        include_raw: bool = False
    ) -> ClassificationResult:
        """
        Classify a single user message (asynchronous).
        
        Args:
            user_message: The user's request to classify
            include_raw: If True, include raw LLM response in result
            
        Returns:
            ClassificationResult with label, confidence, and metadata
        """
        try:
            user_prompt = self._build_prompt(user_message)
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
            return ClassificationResult(
                label=-1,
                confidence=0.0,
                strategy=STRATEGY_NAME,
                error=str(e)
            )
    
    async def classify_batch_async(
        self,
        messages: List[str],
        include_raw: bool = False
    ) -> List[ClassificationResult]:
        """
        Classify a batch of messages (asynchronous, parallel).
        
        Uses semaphore to limit concurrency and avoid rate limiting.
        
        Args:
            messages: List of user messages to classify
            include_raw: If True, include raw LLM responses
            
        Returns:
            List of ClassificationResult objects (in same order as input)
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def classify_with_semaphore(msg: str, idx: int) -> tuple[int, ClassificationResult]:
            async with semaphore:
                result = await self.classify_async(msg, include_raw=include_raw)
                if (idx + 1) % 10 == 0:
                    logger.info(f"Async processed {idx + 1}/{len(messages)} messages")
                return idx, result
        
        # Create tasks
        tasks = [
            classify_with_semaphore(msg, i)
            for i, msg in enumerate(messages)
        ]
        
        # Run all tasks concurrently
        results_with_idx = await asyncio.gather(*tasks)
        
        # Sort by original index
        results_with_idx.sort(key=lambda x: x[0])
        return [r for _, r in results_with_idx]


# =============================================================================
# Convenience Functions
# =============================================================================

def classify_message(user_message: str) -> Dict[str, Any]:
    """Convenience function to classify a single message (sync)."""
    judge = StrategyAJudge()
    result = judge.classify(user_message)
    return result.to_dict()


async def classify_message_async(user_message: str) -> Dict[str, Any]:
    """Convenience function to classify a single message (async)."""
    judge = StrategyAJudge()
    result = await judge.classify_async(user_message)
    return result.to_dict()


# =============================================================================
# Testing
# =============================================================================

if __name__ == "__main__":
    import time
    
    logging.basicConfig(level=logging.INFO)
    
    test_messages = [
        "Fix the authentication bug in the login flow",
        "What is the syntax for a Python list comprehension?",
        "Refactor this module to use dependency injection",
        "Add a comment to line 42",
        "Debug why the tests are failing in CI"
    ]
    
    print("=" * 70)
    print("STRATEGY A: TEXT ONLY - TEST RUN")
    print("=" * 70)
    
    judge = StrategyAJudge()
    
    # Test sync
    print("\n📍 SYNCHRONOUS CLASSIFICATION")
    print("-" * 40)
    start = time.time()
    for msg in test_messages[:2]:
        result = judge.classify(msg, include_raw=True)
        print(f"\nMessage: {msg[:50]}...")
        print(f"Label: {result.label} ({'Reasoning' if result.label == 0 else 'Non-Reasoning'})")
        print(f"Confidence: {result.confidence:.2f}")
    sync_time = time.time() - start
    print(f"\n⏱️ Sync time: {sync_time:.2f}s")
    
    # Test async
    if ASYNC_AVAILABLE:
        print("\n📍 ASYNCHRONOUS CLASSIFICATION (Parallel)")
        print("-" * 40)
        
        async def run_async_test():
            start = time.time()
            results = await judge.classify_batch_async(test_messages, include_raw=False)
            async_time = time.time() - start
            
            for msg, result in zip(test_messages, results):
                print(f"\nMessage: {msg[:50]}...")
                print(f"Label: {result.label} ({'Reasoning' if result.label == 0 else 'Non-Reasoning'})")
                print(f"Confidence: {result.confidence:.2f}")
            
            print(f"\n⏱️ Async time: {async_time:.2f}s")
            print(f"🚀 Speedup: {sync_time * len(test_messages) / 2 / async_time:.1f}x")
        
        asyncio.run(run_async_test())
    else:
        print("\n⚠️ Async not available - skipping async test")
