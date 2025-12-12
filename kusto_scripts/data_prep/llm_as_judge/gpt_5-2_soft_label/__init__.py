"""
GPT-5.2 Soft Label Teacher Module
=================================

A modular async Python package for binary classification with soft-label generation
using Azure OpenAI with logprobs and logit_bias.

Binary Task: "Does this user message require reasoning?"
    - Label 0: Requires reasoning (complex, multi-step, needs planning)
    - Label 1: Does not require reasoning (simple, pattern-matching, boilerplate)

Key Features:
    - Per-turn labeling (each user message in a conversation gets a label)
    - Hard labels (0/1) from generated tokens
    - Soft labels (probability in [0,1]) derived from logprobs
    - Rationales enabled by default (use --no-rationales to disable)
    - Modular strategies for what the LLM sees
    - Azure Blob Storage integration for input data
    - Async processing with concurrency control (semaphore=50)
    - Tenacity retry logic for reliability

Module Structure:
    config.py          - Configuration constants and rate limits
    client.py          - Azure OpenAI client factory + Key Vault
    tokenizer.py       - Token ID resolution using tiktoken
    prompts.py         - System prompts and user templates
    classifier.py      - Core classification with soft labels + tenacity
    rationale.py       - Rationale generation + tenacity
    pipeline.py        - Dataset processing with async concurrency
    cli.py             - Command-line interface
    
    io/                - Input/Output handling
        blob_reader.py - Read from Azure Blob Storage
        schemas.py     - Data schemas (TurnRecord, LabeledTurnRecord)
    
    strategies/        - Labeling strategies (what the LLM sees)
        base.py        - Abstract strategy interface
        user_message_only.py - Strategy A: classify user message in isolation

Usage:
    # Label with rationales (default)
    python -m gpt_5-2_soft_label label \\
        --input data.jsonl \\
        --output labeled.jsonl \\
        --model gpt-5.2

    # Label without rationales (faster)
    python -m gpt_5-2_soft_label label \\
        --input data.jsonl \\
        --output labeled.jsonl \\
        --model gpt-5.2 \\
        --no-rationales

Output Schema (minimal):
    {
        "conversationId": "abc-123",
        "messageId": "msg-456",
        "hard_label": 0,
        "soft_label": 0.23,
        "rationale": "This message requires..."
    }

Author: Azure OpenAI SFT Pipeline
Version: 1.1.0
"""

__version__ = "1.1.0"

# Core exports
from .config import (
    DEFAULT_API_VERSION,
    DEFAULT_CONCURRENCY,
    DEFAULT_LOGIT_BIAS,
    LABEL_REASONING,
    LABEL_NON_REASONING,
)
from .client import get_azure_openai_client, get_api_key_from_keyvault
from .tokenizer import get_label_token_ids, LabelTokenizer
from .prompts import SYSTEM_PROMPT, USER_TEMPLATE, RATIONALE_SYSTEM_PROMPT, RATIONALE_TEMPLATE
from .classifier import classify_message, ClassificationResult
from .rationale import generate_rationale
from .pipeline import label_dataset, label_turns, LabelingStats

# IO exports
from .io.schemas import TurnRecord, LabeledTurnRecord, ConversationRecord
from .io.blob_reader import BlobDataReader, list_available_datasets, download_split

# Strategy exports
from .strategies import get_strategy, STRATEGIES, LabelingStrategy

__all__ = [
    # Version
    "__version__",
    # Config
    "DEFAULT_API_VERSION",
    "DEFAULT_CONCURRENCY", 
    "DEFAULT_LOGIT_BIAS",
    "LABEL_REASONING",
    "LABEL_NON_REASONING",
    # Client
    "get_azure_openai_client",
    "get_api_key_from_keyvault",
    # Tokenizer
    "get_label_token_ids",
    "LabelTokenizer",
    # Prompts
    "SYSTEM_PROMPT",
    "USER_TEMPLATE",
    "RATIONALE_SYSTEM_PROMPT",
    "RATIONALE_TEMPLATE",
    # Classifier
    "classify_message",
    "ClassificationResult",
    # Rationale
    "generate_rationale",
    # Pipeline
    "label_dataset",
    "label_turns",
    "LabelingStats",
    # IO
    "TurnRecord",
    "LabeledTurnRecord",
    "ConversationRecord",
    "BlobDataReader",
    "list_available_datasets",
    "download_split",
    # Strategies
    "get_strategy",
    "STRATEGIES",
    "LabelingStrategy",
]
