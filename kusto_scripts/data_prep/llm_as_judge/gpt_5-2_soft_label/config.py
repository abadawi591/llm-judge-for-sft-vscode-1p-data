"""
Configuration Module
====================

Centralized configuration constants and defaults for the soft-label teacher pipeline.

This module defines:
    - Azure OpenAI API settings
    - Label semantics and mappings
    - Logit bias configuration for constrained generation
    - Concurrency and retry settings

Label Semantics:
    The binary classification task determines whether a user message requires
    multi-step reasoning or can be handled with simple pattern matching.
    
    Label 0 (REASONING):
        - Complex queries requiring planning, synthesis, or chain-of-thought
        - Multi-step problems, code refactoring, architecture decisions
        - Examples: "Refactor this codebase to use async/await patterns"
    
    Label 1 (NON_REASONING):
        - Simple queries answerable via pattern matching or boilerplate
        - Trivial computations, simple explanations, code snippets
        - Examples: "How do I create a list in Python?"

Logit Bias Strategy:
    We use logit_bias to concentrate probability mass on tokens "0" and "1".
    A bias of +5 multiplies the odds by exp(5) ≈ 148x, making other tokens
    extremely unlikely while preserving the relative preference between 0 and 1.
    This gives us meaningful soft labels from the logprobs.
"""

from typing import Dict

# =============================================================================
# Azure OpenAI API Configuration
# =============================================================================

# Default API version for Azure OpenAI
# Use 2025-04-01-preview for latest features including logprobs
DEFAULT_API_VERSION: str = "2025-04-01-preview"

# Azure Key Vault configuration for API key retrieval
KEYVAULT_NAME: str = "abadawikeys"
KEYVAULT_SECRET_NAME: str = "gpt-5-2-api-key"

# Azure OpenAI endpoint
AZURE_OPENAI_ENDPOINT: str = "https://deepprompteastus2.openai.azure.com"

# Default deployment/model name
DEFAULT_MODEL: str = "gpt-5.2"

# =============================================================================
# Label Definitions
# =============================================================================

# Label values
LABEL_REASONING: int = 0      # Requires reasoning (complex)
LABEL_NON_REASONING: int = 1  # Does not require reasoning (simple)

# Human-readable label names
LABEL_NAMES: Dict[int, str] = {
    LABEL_REASONING: "reasoning",
    LABEL_NON_REASONING: "non_reasoning",
}

# Token strings corresponding to labels
TOKEN_LABEL_0: str = "0"
TOKEN_LABEL_1: str = "1"

# =============================================================================
# Logit Bias Configuration
# =============================================================================

# Logit bias value to apply to label tokens
# +5 bias multiplies odds by exp(5) ≈ 148x
# This concentrates probability mass on "0" and "1" tokens while
# preserving the model's relative preference between them
DEFAULT_LOGIT_BIAS: float = 5.0

# =============================================================================
# Generation Parameters
# =============================================================================

# Classification call parameters
CLASSIFICATION_MAX_TOKENS: int = 1
CLASSIFICATION_TEMPERATURE: float = 1.0  # Use temp=1 for meaningful logprobs
CLASSIFICATION_TOP_LOGPROBS: int = 5

# Rationale call parameters
RATIONALE_MAX_TOKENS: int = 128
RATIONALE_TEMPERATURE: float = 0.7

# =============================================================================
# Rate Limits (from Azure OpenAI deployment: gpt-5.2)
# =============================================================================

# Deployment rate limits (Global Standard tier)
RATE_LIMIT_REQUESTS_PER_MINUTE: int = 10_000
RATE_LIMIT_TOKENS_PER_MINUTE: int = 1_000_000

# Estimated tokens per request
TOKENS_PER_CLASSIFICATION: int = 200   # ~200 input + 1 output
TOKENS_PER_RATIONALE: int = 150        # ~150 output tokens
TOKENS_PER_REQUEST_WITH_RATIONALE: int = 350  # classification + rationale

# =============================================================================
# Concurrency Configuration
# =============================================================================

# Calculated safe concurrency:
# - Token limit: 1,000,000 / 350 ≈ 2,857 requests/min
# - Request limit: 10,000 requests/min
# - Bottleneck: Token limit
# - Safe rate: ~1,000 requests/min (35% of limit for headroom)
# - With ~3s avg latency: 50 concurrent = ~1,000 requests/min

DEFAULT_CONCURRENCY: int = 50   # Optimal for gpt-5.2 deployment
MAX_CONCURRENCY: int = 100      # Hard cap to prevent rate limit issues

# =============================================================================
# Retry Configuration (tenacity)
# =============================================================================

MAX_RETRIES: int = 5              # Increased for production reliability
RETRY_MIN_WAIT: float = 1.0       # Initial backoff (seconds)
RETRY_MAX_WAIT: float = 60.0      # Max backoff (seconds)
RETRY_MULTIPLIER: float = 2.0     # Exponential backoff multiplier

# Retry on these HTTP status codes
RETRY_STATUS_CODES: list = [429, 500, 502, 503, 504]

# =============================================================================
# Azure Blob Storage Configuration
# =============================================================================

# Storage account and container
BLOB_STORAGE_ACCOUNT_URL: str = "https://githubtelemetry.blob.core.windows.net"
BLOB_CONTAINER_NAME: str = "github-copilot-sft-data-all-languages"
BLOB_BASE_PATH: str = "experiments/testvscode_test/v4"

# Output folder naming
LABELED_FOLDER_PREFIX: str = "LABELED_"

# Bucket files (stratification by conversation length)
BUCKET_FILES: list = [
    "short_3_to_5_turns",
    "medium_6_to_10_turns",
    "long_11_to_20_turns",
]

# Data splits
DATA_SPLITS: list = ["train", "val", "test"]

# =============================================================================
# Output Schema Field Names
# =============================================================================

# Fields in the output JSONL
OUTPUT_FIELD_CONVERSATION_ID: str = "conversationId"
OUTPUT_FIELD_MESSAGE_ID: str = "messageId"
OUTPUT_FIELD_SPLIT: str = "split"
OUTPUT_FIELD_BUCKET: str = "bucket"
OUTPUT_FIELD_HARD_LABEL: str = "hard_label"
OUTPUT_FIELD_SOFT_LABEL: str = "soft_label"  # Single field: P(non-reasoning)
OUTPUT_FIELD_RATIONALE: str = "rationale"
OUTPUT_FIELD_ERROR: str = "labeling_error"

