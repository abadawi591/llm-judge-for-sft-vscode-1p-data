"""
Tokenizer Module
================

Token ID resolution for logit_bias configuration using tiktoken.

This module provides:
    - Token ID lookup for label tokens "0" and "1"
    - Encoding selection based on model name
    - Validation that tokens encode to single IDs

Why Token IDs Matter:
    The logit_bias parameter in OpenAI's API requires token IDs (integers),
    not token strings. To bias the model toward generating "0" or "1",
    we need the exact token IDs used by the model's tokenizer.

Tokenizer Selection:
    - GPT-4, GPT-4-Turbo, GPT-4o, GPT-5.x: cl100k_base encoding
    - GPT-3.5-Turbo: cl100k_base encoding
    - Legacy models (GPT-3, text-davinci): p50k_base or r50k_base
    
    For Azure OpenAI deployments, the encoding depends on the underlying
    model, not the deployment name. GPT-5.2 uses cl100k_base.

Token Verification:
    For cl100k_base encoding:
    - "0" encodes to token ID 15 (single token)
    - "1" encodes to token ID 16 (single token)
    
    These are verified at runtime to catch any tokenizer version issues.
"""

from typing import Tuple, Optional
from dataclasses import dataclass

# tiktoken is optional - we provide fallback values
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


# =============================================================================
# Known Token IDs (verified for cl100k_base encoding)
# =============================================================================

# Token IDs for "0" and "1" in cl100k_base encoding
# These are used as fallback if tiktoken is not installed
CL100K_TOKEN_ID_0: int = 15
CL100K_TOKEN_ID_1: int = 16


@dataclass
class LabelTokenizer:
    """
    Encapsulates token IDs for binary classification labels.
    
    This dataclass holds the token IDs for labels "0" and "1" along with
    metadata about how they were resolved (tiktoken vs fallback).
    
    Attributes:
        token_id_0: Token ID for label "0" (reasoning required)
        token_id_1: Token ID for label "1" (no reasoning required)
        encoding_name: Name of the tiktoken encoding used (e.g., "cl100k_base")
        verified: Whether the token IDs were verified via tiktoken
    
    Example:
        >>> tokenizer = get_label_token_ids(model="gpt-5.2")
        >>> print(f"Token ID for '0': {tokenizer.token_id_0}")
        >>> print(f"Token ID for '1': {tokenizer.token_id_1}")
        Token ID for '0': 15
        Token ID for '1': 16
    """
    token_id_0: int
    token_id_1: int
    encoding_name: str
    verified: bool
    
    def as_tuple(self) -> Tuple[int, int]:
        """Return token IDs as (id_0, id_1) tuple for unpacking."""
        return (self.token_id_0, self.token_id_1)
    
    def get_logit_bias(self, bias_value: float = 5.0) -> dict:
        """
        Generate logit_bias dict for API calls.
        
        Args:
            bias_value: Logit bias to apply (default: 5.0)
                       +5 multiplies odds by exp(5) ≈ 148x
        
        Returns:
            Dict mapping token IDs to bias values
        
        Example:
            >>> tokenizer.get_logit_bias(5.0)
            {15: 5.0, 16: 5.0}
        """
        return {
            self.token_id_0: bias_value,
            self.token_id_1: bias_value,
        }


def _get_encoding_for_model(model: str) -> str:
    """
    Determine the tiktoken encoding name for a given model.
    
    Args:
        model: Model name or Azure deployment name
    
    Returns:
        Encoding name (e.g., "cl100k_base")
    
    Note:
        Azure deployment names may not match model names.
        We use pattern matching and default to cl100k_base for modern models.
    """
    model_lower = model.lower()
    
    # GPT-4 family and newer (including GPT-5.x) use cl100k_base
    if any(prefix in model_lower for prefix in ["gpt-4", "gpt-5", "gpt4", "gpt5"]):
        return "cl100k_base"
    
    # GPT-3.5-Turbo uses cl100k_base
    if "gpt-3.5" in model_lower or "gpt-35" in model_lower:
        return "cl100k_base"
    
    # Default to cl100k_base for unknown models (safest for modern deployments)
    return "cl100k_base"


def get_label_token_ids(
    model: str = "gpt-5.2",
    verify: bool = True,
) -> LabelTokenizer:
    """
    Get token IDs for classification labels "0" and "1".
    
    This function resolves the exact token IDs needed for logit_bias
    configuration. It uses tiktoken if available, otherwise falls back
    to known values for cl100k_base encoding.
    
    Args:
        model: Model name or Azure deployment name (default: "gpt-5.2")
        verify: Whether to verify token encoding round-trips (default: True)
    
    Returns:
        LabelTokenizer: Dataclass containing token IDs and metadata
    
    Raises:
        ValueError: If verification fails (token doesn't encode to single ID)
    
    Example:
        >>> tokenizer = get_label_token_ids(model="gpt-5.2")
        >>> print(f"Encoding: {tokenizer.encoding_name}")
        >>> print(f"Token '0' -> ID {tokenizer.token_id_0}")
        >>> print(f"Token '1' -> ID {tokenizer.token_id_1}")
        Encoding: cl100k_base
        Token '0' -> ID 15
        Token '1' -> ID 16
        
        >>> # Use with API call
        >>> logit_bias = tokenizer.get_logit_bias(5.0)
        >>> # {15: 5.0, 16: 5.0}
    
    Note:
        For GPT-4/5.x models using cl100k_base:
        - "0" = token ID 15
        - "1" = token ID 16
        
        These are single-character tokens, so they encode to exactly one ID.
    """
    encoding_name = _get_encoding_for_model(model)
    
    if TIKTOKEN_AVAILABLE:
        # Use tiktoken for accurate token ID resolution
        encoding = tiktoken.get_encoding(encoding_name)
        
        # Encode label tokens
        ids_0 = encoding.encode("0")
        ids_1 = encoding.encode("1")
        
        # Verify single-token encoding
        if verify:
            if len(ids_0) != 1:
                raise ValueError(
                    f"Token '0' encodes to {len(ids_0)} tokens {ids_0}, expected 1. "
                    f"Encoding: {encoding_name}"
                )
            if len(ids_1) != 1:
                raise ValueError(
                    f"Token '1' encodes to {len(ids_1)} tokens {ids_1}, expected 1. "
                    f"Encoding: {encoding_name}"
                )
        
        token_id_0 = ids_0[0]
        token_id_1 = ids_1[0]
        verified = True
        
        # Double-check against known values
        if encoding_name == "cl100k_base":
            if token_id_0 != CL100K_TOKEN_ID_0:
                print(f"⚠ Warning: Token '0' ID {token_id_0} differs from expected {CL100K_TOKEN_ID_0}")
            if token_id_1 != CL100K_TOKEN_ID_1:
                print(f"⚠ Warning: Token '1' ID {token_id_1} differs from expected {CL100K_TOKEN_ID_1}")
    
    else:
        # Fallback to known values
        print(
            "⚠ tiktoken not installed, using hardcoded token IDs for cl100k_base. "
            "Install with: pip install tiktoken"
        )
        token_id_0 = CL100K_TOKEN_ID_0
        token_id_1 = CL100K_TOKEN_ID_1
        verified = False
    
    return LabelTokenizer(
        token_id_0=token_id_0,
        token_id_1=token_id_1,
        encoding_name=encoding_name,
        verified=verified,
    )


def validate_token_ids(tokenizer: LabelTokenizer) -> bool:
    """
    Validate that token IDs can be used for classification.
    
    Args:
        tokenizer: LabelTokenizer instance to validate
    
    Returns:
        bool: True if valid, False otherwise
    
    Example:
        >>> tokenizer = get_label_token_ids()
        >>> is_valid = validate_token_ids(tokenizer)
        >>> print(f"Token IDs valid: {is_valid}")
    """
    # Check that IDs are positive integers
    if not isinstance(tokenizer.token_id_0, int) or tokenizer.token_id_0 < 0:
        return False
    if not isinstance(tokenizer.token_id_1, int) or tokenizer.token_id_1 < 0:
        return False
    
    # Check that IDs are different
    if tokenizer.token_id_0 == tokenizer.token_id_1:
        return False
    
    return True

