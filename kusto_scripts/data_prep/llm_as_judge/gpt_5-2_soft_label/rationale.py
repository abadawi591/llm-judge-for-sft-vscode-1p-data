"""
Rationale Module
================

Rationale generation for human inspection of classification decisions.

This module provides a SEPARATE API call to generate natural-language
explanations for classification decisions. The rationale is intentionally
decoupled from the classification call to:

1. Preserve Logprob Quality:
   Adding explanation tokens would shift probability mass and corrupt
   the soft-label computation. By keeping classification single-token,
   we get clean, interpretable logprobs.

2. Avoid Confirmation Bias:
   The classification is made first without seeing any rationale.
   The rationale is generated post-hoc and cannot influence the label.

3. Human Interpretability:
   Rationales help humans understand why the model made a decision,
   useful for quality assurance and debugging.

NOTE: Rationales are now ENABLED BY DEFAULT in the pipeline.
Use --no-rationales flag to disable them.
"""

from openai import AsyncAzureOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .config import (
    RATIONALE_MAX_TOKENS,
    RATIONALE_TEMPERATURE,
    MAX_RETRIES,
    RETRY_MIN_WAIT,
    RETRY_MAX_WAIT,
    RETRY_MULTIPLIER,
)
from .prompts import get_rationale_messages


# Retry decorator for API calls
_retry_decorator = retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(
        multiplier=RETRY_MULTIPLIER,
        min=RETRY_MIN_WAIT,
        max=RETRY_MAX_WAIT,
    ),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, APIError)),
    reraise=True,
)


@_retry_decorator
async def _call_rationale_api(
    client: AsyncAzureOpenAI,
    messages: list,
    model: str,
) -> str:
    """
    Make the rationale API call with retry logic.
    
    Args:
        client: AsyncAzureOpenAI client
        messages: Chat messages list
        model: Deployment name
    
    Returns:
        Rationale text string
    
    Raises:
        RateLimitError: After max retries on 429
        APIError: After max retries on other API errors
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=RATIONALE_MAX_TOKENS,
        temperature=RATIONALE_TEMPERATURE,
    )
    
    rationale = response.choices[0].message.content
    return rationale.strip() if rationale else ""


async def generate_rationale(
    client: AsyncAzureOpenAI,
    user_message: str,
    model: str,
    label: int,
) -> str:
    """
    Generate a natural-language rationale for a classification decision.
    
    This function makes a SEPARATE API call (distinct from classification)
    to produce a human-readable explanation. The rationale helps humans
    understand why a particular label was assigned.
    
    Args:
        client: AsyncAzureOpenAI client instance
        user_message: The user message that was classified
        model: Azure deployment name (e.g., "gpt-5.2")
        label: The hard label assigned (0 or 1)
            - 0 = requires reasoning
            - 1 = does not require reasoning
    
    Returns:
        str: Natural-language rationale (2-4 sentences)
    
    Raises:
        RateLimitError: After max retries exhausted
        APIError: On unrecoverable API errors
    
    Example:
        >>> rationale = await generate_rationale(
        ...     client=client,
        ...     user_message="How do I create a Python list?",
        ...     model="gpt-5.2",
        ...     label=1,
        ... )
        >>> print(rationale)
        "This question asks for basic Python syntax, which can be answered
        with a simple code snippet. No multi-step reasoning or planning is
        required."
    
    Note:
        Rationale generation is intentionally separate from classification to:
        1. Preserve logprob quality for soft labels
        2. Avoid confirmation bias in classification
        
        Each rationale uses ~150 output tokens vs 1 for classification.
    """
    # Build messages for rationale request
    messages = get_rationale_messages(user_message, label)
    
    # Make API call with retry
    return await _call_rationale_api(client, messages, model)


# Alias for backward compatibility
get_rationale_for_message = generate_rationale
