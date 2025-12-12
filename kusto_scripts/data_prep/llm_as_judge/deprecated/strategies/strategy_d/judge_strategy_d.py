"""
Strategy D: Text + Conversation History LLM Judge

Supports both sync and async API calls with tenacity retry logic.

This strategy uses conversation history for context-aware classification.

Labels:
    0 = Reasoning Required
    1 = Non-Reasoning Sufficient

Usage:
    # Synchronous
    from strategies.strategy_d.judge_strategy_d import StrategyDJudge
    judge = StrategyDJudge()
    result = judge.classify_turn(turns=turns, turn_index=7)
    
    # Asynchronous
    result = await judge.classify_turn_async(turns=turns, turn_index=7)
    
    # Batch async (parallel)
    results = await judge.classify_conversation_async(conversation)
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

STRATEGY_NAME = "D"
STRATEGY_DESCRIPTION = "Text + Conversation History"

MAX_RETRIES = 5
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 60
DEFAULT_BATCH_CONCURRENCY = 10

SYSTEM_PROMPT = """You are classifying whether the CURRENT user request requires a reasoning-capable LLM.
You have access to conversation history to understand context.

CLASSIFICATION LABELS:
- 0 = REASONING REQUIRED: Builds on complex prior work, references previous decisions, debugging prior changes, continuing multi-step implementation
- 1 = NON-REASONING SUFFICIENT: Independent of context, simple follow-up, new unrelated topic, basic clarifying questions

KEY CONSIDERATIONS:
1. Does this request BUILD on previous context in complex ways?
2. Would a model WITHOUT this history misunderstand the request?
3. Is there accumulated state (files modified, decisions made)?
4. Is this a simple follow-up or a new complex direction?

OUTPUT FORMAT (exactly two lines):
Line 1: Label (0 or 1)
Line 2: Confidence (decimal between 0.0 and 1.0)"""

USER_PROMPT_TEMPLATE = """═══════════════════════════════════════════════════════════════════════════
CONVERSATION METADATA
═══════════════════════════════════════════════════════════════════════════
- Total turns in conversation: {total_turns}
- Current turn: {current_turn_index}

═══════════════════════════════════════════════════════════════════════════
CONVERSATION HISTORY (last {n_context} turns)
═══════════════════════════════════════════════════════════════════════════
{formatted_history}

═══════════════════════════════════════════════════════════════════════════
CURRENT REQUEST (Turn {current_turn_index})
═══════════════════════════════════════════════════════════════════════════
User: {current_user_message}"""


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
    turn_index: Optional[int] = None
    conversation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "turn_index": self.turn_index,
            "conversation_id": self.conversation_id,
            "raw_response": self.raw_response,
            "error": self.error
        }


@dataclass
class Turn:
    """A single turn in a conversation."""
    turn_index: int
    user_message: str
    model_message: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Turn":
        return cls(
            turn_index=data.get("turnIndex", 0),
            user_message=data.get("userMessage", ""),
            model_message=data.get("modelMessage", "")
        )


# =============================================================================
# Main Judge Class
# =============================================================================

class StrategyDJudge:
    """
    LLM Judge using Strategy D: Text + Conversation History.
    Supports both synchronous and asynchronous API calls.
    """
    
    def __init__(
        self,
        use_keyvault: bool = True,
        max_tokens: int = 50,
        temperature: float = 0.0,
        max_history_turns: int = 5,
        max_response_length: int = 500,
        max_concurrency: int = DEFAULT_BATCH_CONCURRENCY
    ):
        self.use_keyvault = use_keyvault
        self.model = get_model_name()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_history_turns = max_history_turns
        self.max_response_length = max_response_length
        self.max_concurrency = max_concurrency
        
        self._sync_client = None
        self._async_client = None
        
        logger.info(f"Initialized Strategy D Judge with model: {self.model}")
    
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
    
    def _get_context_window(self, turns: List[Turn], current_idx: int) -> List[Turn]:
        """Select which turns to include in context."""
        if current_idx <= 3:
            return turns[:current_idx]
        elif current_idx <= 10:
            start = max(0, current_idx - self.max_history_turns)
            return turns[start:current_idx]
        else:
            first_turn = [turns[0]] if turns else []
            recent = turns[current_idx - (self.max_history_turns - 1):current_idx]
            return first_turn + recent
    
    def _format_turn(self, turn: Turn) -> str:
        response = turn.model_message
        if len(response) > self.max_response_length:
            response = response[:self.max_response_length] + "... [truncated]"
        
        return f"""[Turn {turn.turn_index + 1}]
User: {turn.user_message}
Assistant: {response}
"""
    
    def _format_history(self, context_turns: List[Turn]) -> str:
        if not context_turns:
            return "(No previous turns - this is the first message)"
        return "\n".join(self._format_turn(t) for t in context_turns)
    
    def _build_prompt(
        self,
        current_message: str,
        context_turns: List[Turn],
        current_turn_index: int,
        total_turns: int
    ) -> str:
        max_len = config.labeling.max_message_length
        if len(current_message) > max_len:
            current_message = current_message[:max_len] + "... [truncated]"
        
        formatted_history = self._format_history(context_turns)
        
        return USER_PROMPT_TEMPLATE.format(
            total_turns=total_turns,
            current_turn_index=current_turn_index + 1,
            n_context=len(context_turns),
            formatted_history=formatted_history,
            current_user_message=current_message
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
    
    def classify_turn(
        self,
        turns: List[Dict[str, Any]],
        turn_index: int,
        conversation_id: Optional[str] = None,
        include_raw: bool = False
    ) -> ClassificationResult:
        """Classify a specific turn within a conversation (sync)."""
        try:
            turn_objects = [Turn.from_dict(t) for t in turns]
            total_turns = len(turn_objects)
            
            if turn_index >= total_turns:
                raise ValueError(f"Turn index {turn_index} out of range (total: {total_turns})")
            
            current_turn = turn_objects[turn_index]
            context_turns = self._get_context_window(turn_objects, turn_index)
            
            user_prompt = self._build_prompt(
                current_message=current_turn.user_message,
                context_turns=context_turns,
                current_turn_index=turn_index,
                total_turns=total_turns
            )
            
            response_text = self._call_api_sync(user_prompt)
            label, confidence = self._parse_response(response_text)
            
            return ClassificationResult(
                label=label,
                confidence=confidence,
                strategy=STRATEGY_NAME,
                turn_index=turn_index,
                conversation_id=conversation_id,
                raw_response=response_text if include_raw else None
            )
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return ClassificationResult(
                label=-1, confidence=0.0, strategy=STRATEGY_NAME,
                turn_index=turn_index, conversation_id=conversation_id, error=str(e)
            )
    
    def classify_conversation(
        self,
        conversation: Dict[str, Any],
        include_raw: bool = False
    ) -> List[ClassificationResult]:
        """Classify all turns in a conversation (sync)."""
        conversation_id = conversation.get("conversationId")
        turns = conversation.get("turnsArray", [])
        
        results = []
        for i in range(len(turns)):
            result = self.classify_turn(
                turns=turns,
                turn_index=i,
                conversation_id=conversation_id,
                include_raw=include_raw
            )
            results.append(result)
        
        return results
    
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
    
    async def classify_turn_async(
        self,
        turns: List[Dict[str, Any]],
        turn_index: int,
        conversation_id: Optional[str] = None,
        include_raw: bool = False
    ) -> ClassificationResult:
        """Classify a specific turn within a conversation (async)."""
        try:
            turn_objects = [Turn.from_dict(t) for t in turns]
            total_turns = len(turn_objects)
            
            if turn_index >= total_turns:
                raise ValueError(f"Turn index {turn_index} out of range")
            
            current_turn = turn_objects[turn_index]
            context_turns = self._get_context_window(turn_objects, turn_index)
            
            user_prompt = self._build_prompt(
                current_message=current_turn.user_message,
                context_turns=context_turns,
                current_turn_index=turn_index,
                total_turns=total_turns
            )
            
            response_text = await self._call_api_async(user_prompt)
            label, confidence = self._parse_response(response_text)
            
            return ClassificationResult(
                label=label,
                confidence=confidence,
                strategy=STRATEGY_NAME,
                turn_index=turn_index,
                conversation_id=conversation_id,
                raw_response=response_text if include_raw else None
            )
        except Exception as e:
            logger.error(f"Async classification failed: {e}")
            return ClassificationResult(
                label=-1, confidence=0.0, strategy=STRATEGY_NAME,
                turn_index=turn_index, conversation_id=conversation_id, error=str(e)
            )
    
    async def classify_conversation_async(
        self,
        conversation: Dict[str, Any],
        include_raw: bool = False
    ) -> List[ClassificationResult]:
        """Classify all turns in a conversation (async, parallel)."""
        conversation_id = conversation.get("conversationId")
        turns = conversation.get("turnsArray", [])
        
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def classify_with_semaphore(turn_idx: int) -> tuple[int, ClassificationResult]:
            async with semaphore:
                result = await self.classify_turn_async(
                    turns=turns,
                    turn_index=turn_idx,
                    conversation_id=conversation_id,
                    include_raw=include_raw
                )
                return turn_idx, result
        
        tasks = [classify_with_semaphore(i) for i in range(len(turns))]
        results_with_idx = await asyncio.gather(*tasks)
        results_with_idx.sort(key=lambda x: x[0])
        return [r for _, r in results_with_idx]


# =============================================================================
# Convenience Functions
# =============================================================================

def classify_turn_with_history(turns: List[Dict[str, Any]], turn_index: int) -> Dict[str, Any]:
    """Convenience function for Strategy D classification with history."""
    judge = StrategyDJudge()
    result = judge.classify_turn(turns, turn_index)
    return result.to_dict()


async def classify_turn_with_history_async(turns: List[Dict[str, Any]], turn_index: int) -> Dict[str, Any]:
    """Convenience function for async Strategy D classification."""
    judge = StrategyDJudge()
    result = await judge.classify_turn_async(turns, turn_index)
    return result.to_dict()

