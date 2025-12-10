"""
Configuration Settings for LLM-as-Judge Labeling System

This module contains all configurable settings for the labeling pipeline.
"""

from dataclasses import dataclass
from typing import List, Optional


# =============================================================================
# Model Configuration
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for the LLM judge model."""
    
    model_name: str = "claude-sonnet-4-5"
    max_tokens: int = 50  # Short output: just "0" or "1" plus confidence
    temperature: float = 0.0  # Deterministic for consistency
    
    # Rate limiting
    requests_per_minute: int = 150
    tokens_per_minute: int = 150_000


# =============================================================================
# Labeling Configuration
# =============================================================================

@dataclass
class LabelingConfig:
    """Configuration for the labeling process."""
    
    # Output labels
    LABEL_REASONING: int = 0
    LABEL_NON_REASONING: int = 1
    
    # Confidence thresholds
    high_confidence_threshold: float = 0.85
    low_confidence_threshold: float = 0.60
    
    # Context settings for Strategy C
    max_history_turns: int = 5  # Maximum previous turns to include
    max_message_length: int = 2000  # Truncate long messages
    max_response_length: int = 500  # Truncate long assistant responses
    
    # Batch processing
    batch_size: int = 100
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


# =============================================================================
# Strategy-Specific Settings
# =============================================================================

@dataclass
class StrategyAConfig:
    """Settings for Strategy A: Text Only."""
    
    name: str = "A"
    description: str = "Text Only (Baseline)"
    cost_per_call: float = 0.001  # Estimated USD


@dataclass
class StrategyBConfig:
    """Settings for Strategy B: Text + Behavioral Metrics."""
    
    name: str = "B"
    description: str = "Text + Behavioral Metrics"
    cost_per_call: float = 0.002  # Estimated USD
    
    # Behavioral signal thresholds (for prompt guidance)
    high_completion_tokens: int = 1500
    low_completion_tokens: int = 500
    high_llm_calls: int = 3
    long_duration_ms: int = 30_000


@dataclass
class StrategyCConfig:
    """Settings for Strategy C: Text + Conversation History."""
    
    name: str = "C"
    description: str = "Text + Conversation History"
    cost_per_call: float = 0.005  # Estimated USD
    
    # Context window settings
    short_convo_turns: int = 3  # Include all turns for short convos
    medium_convo_turns: int = 10  # Include last 5 turns
    long_convo_turns: int = 11  # Include turn 1 + last 4 turns


# =============================================================================
# Voting Configuration
# =============================================================================

@dataclass
class VotingConfig:
    """Configuration for multi-judge voting."""
    
    # Voting strategies
    strategies: List[str] = None  # e.g., ["A", "B", "C"]
    
    # Voting method: "majority", "weighted", "unanimous"
    method: str = "weighted"
    
    # Weights for weighted voting (must sum to 1.0)
    strategy_weights: dict = None
    
    # Confidence threshold for single-strategy bypass
    # If any strategy is above this threshold, skip voting
    bypass_threshold: float = 0.95
    
    def __post_init__(self):
        if self.strategies is None:
            self.strategies = ["A", "B", "C"]
        if self.strategy_weights is None:
            # Strategy C gets more weight (best accuracy)
            self.strategy_weights = {"A": 0.2, "B": 0.3, "C": 0.5}


# =============================================================================
# Output Configuration
# =============================================================================

@dataclass
class OutputConfig:
    """Configuration for output format and storage."""
    
    # Output format
    output_format: str = "jsonl"  # "jsonl" or "parquet"
    
    # Include fields in output
    include_raw_response: bool = False  # Save full LLM response
    include_prompt: bool = False  # Save the prompt used
    include_model_info: bool = True  # Include model name, version
    
    # File naming
    output_prefix: str = "labeled"
    timestamp_format: str = "%Y%m%d_%H%M%S"


# =============================================================================
# Default Configuration Instance
# =============================================================================

class Config:
    """Main configuration container."""
    
    model = ModelConfig()
    labeling = LabelingConfig()
    strategy_a = StrategyAConfig()
    strategy_b = StrategyBConfig()
    strategy_c = StrategyCConfig()
    voting = VotingConfig()
    output = OutputConfig()


# Global config instance
config = Config()

