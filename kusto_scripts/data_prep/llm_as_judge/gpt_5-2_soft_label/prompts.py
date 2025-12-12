"""
Prompts Module
==============

System prompts and user message templates for classification and rationale generation.

This module defines the prompts used in two distinct API calls:

1. Classification Call (get_soft_label_for_message):
   - Uses SYSTEM_PROMPT and USER_TEMPLATE
   - Outputs exactly one token: "0" or "1"
   - Used with logprobs to extract soft labels
   - Must NOT contain any explanation or rationale

2. Rationale Call (get_rationale_for_message):
   - Uses RATIONALE_SYSTEM_PROMPT and RATIONALE_TEMPLATE
   - Produces human-readable explanation
   - For inspection/debugging only
   - Intentionally separate to avoid polluting logprobs

Label Semantics:
    - "0" (REASONING): Message requires multi-step or chain-of-thought reasoning.
      Examples: complex refactoring, architecture decisions, debugging intricate issues.
    
    - "1" (NON_REASONING): Message can be handled with pattern matching or boilerplate.
      Examples: simple syntax questions, code snippets, basic explanations.

Prompt Design Principles:
    1. Classification prompt forces single-token output (no explanation)
    2. Labels are explicitly defined with clear semantics
    3. Rationale prompt is separate to preserve logprob quality
    4. User message is clearly delimited for consistent parsing
"""

# =============================================================================
# Classification Prompts
# =============================================================================

SYSTEM_PROMPT: str = """You are a classifier for VS Code Copilot / agent-mode user messages.

Your task is to decide whether answering a given user message requires multi-step or chain-of-thought reasoning (class 0) or not (class 1).

Semantics:
- Class 0 (token "0"): REQUIRES reasoning. The message is complex, multi-step, or needs planning, synthesis, or long-context reasoning.
- Class 1 (token "1"): DOES NOT require reasoning. The message can be handled by pattern-matching, boilerplate generation, simple explanation, or trivial computation.

Output rules:
- You MUST output ONLY a single token: "0" or "1".
- Do NOT output explanations, words, or punctuation.
- "0" means REQUIRES reasoning.
- "1" means DOES NOT require reasoning."""


USER_TEMPLATE: str = """USER_MESSAGE:
{user_message}"""


# =============================================================================
# Rationale Prompts
# =============================================================================

RATIONALE_SYSTEM_PROMPT: str = """You are an analyst explaining classification decisions.

You will be given a user message and a binary label:
- 0 = requires reasoning
- 1 = does not require reasoning

Explain briefly (2–4 sentences) why this label is appropriate."""


RATIONALE_TEMPLATE: str = """USER_MESSAGE:
{user_message}

LABEL: {label}"""


# =============================================================================
# Prompt Formatting Functions
# =============================================================================

def format_classification_user_message(user_message: str) -> str:
    """
    Format a user message for the classification prompt.
    
    Args:
        user_message: The raw user message to classify
    
    Returns:
        Formatted string ready to use as the user message in API call
    
    Example:
        >>> formatted = format_classification_user_message("How do I sort a list?")
        >>> print(formatted)
        USER_MESSAGE:
        How do I sort a list?
    """
    return USER_TEMPLATE.format(user_message=user_message)


def format_rationale_user_message(user_message: str, label: int) -> str:
    """
    Format a user message and label for the rationale prompt.
    
    Args:
        user_message: The raw user message that was classified
        label: The classification result (0 or 1)
    
    Returns:
        Formatted string ready to use as the user message in API call
    
    Example:
        >>> formatted = format_rationale_user_message("How do I sort a list?", 1)
        >>> print(formatted)
        USER_MESSAGE:
        How do I sort a list?
        
        LABEL: 1
    """
    return RATIONALE_TEMPLATE.format(user_message=user_message, label=label)


def get_classification_messages(user_message: str) -> list:
    """
    Build the complete messages list for a classification API call.
    
    Args:
        user_message: The raw user message to classify
    
    Returns:
        List of message dicts ready for chat.completions.create()
    
    Example:
        >>> messages = get_classification_messages("How do I sort a list?")
        >>> # Use in API call:
        >>> response = await client.chat.completions.create(
        ...     model="gpt-5.2",
        ...     messages=messages,
        ...     max_tokens=1
        ... )
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": format_classification_user_message(user_message)},
    ]


def get_rationale_messages(user_message: str, label: int) -> list:
    """
    Build the complete messages list for a rationale API call.
    
    Args:
        user_message: The raw user message that was classified
        label: The classification result (0 or 1)
    
    Returns:
        List of message dicts ready for chat.completions.create()
    
    Example:
        >>> messages = get_rationale_messages("How do I sort a list?", 1)
        >>> response = await client.chat.completions.create(
        ...     model="gpt-5.2",
        ...     messages=messages,
        ...     max_tokens=128
        ... )
    """
    return [
        {"role": "system", "content": RATIONALE_SYSTEM_PROMPT},
        {"role": "user", "content": format_rationale_user_message(user_message, label)},
    ]

