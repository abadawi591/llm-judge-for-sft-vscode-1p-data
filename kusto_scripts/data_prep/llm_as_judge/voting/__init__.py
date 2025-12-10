"""
Voting strategies for combining multiple LLM judge decisions.
"""

from .ensemble import (
    EnsembleJudge,
    CascadeJudge,
    EnsembleResult,
    VotingMethod,
    majority_vote,
    weighted_vote,
    confidence_vote
)

__all__ = [
    "EnsembleJudge",
    "CascadeJudge",
    "EnsembleResult",
    "VotingMethod",
    "majority_vote",
    "weighted_vote",
    "confidence_vote"
]

