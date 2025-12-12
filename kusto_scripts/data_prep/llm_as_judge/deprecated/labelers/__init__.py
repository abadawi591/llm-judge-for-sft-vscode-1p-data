"""
Labelers for LLM-as-Judge.

Two modes:
- HardLabeler: Discrete labels (0 or 1) - for classification
- SoftLabeler: Probability distribution - for SFT/KD
"""

from .base import BaseLabeler, LabelResult
from .hard_labeler import HardLabeler
from .soft_labeler import SoftLabeler

__all__ = [
    "BaseLabeler",
    "LabelResult",
    "HardLabeler",
    "SoftLabeler"
]

