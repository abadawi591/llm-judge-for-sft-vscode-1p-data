"""
Labeling strategies for LLM-as-Judge.

Available strategies:
- Strategy A: Text Only (baseline, deployment-ready)
- Strategy B: Text + Core Metrics (tokens, duration, LLM calls)
- Strategy C: Text + Core Metrics + Tools (full behavioral signal)
- Strategy D: Text + Conversation History (multi-turn context)
"""

from .strategy_a.judge_strategy_a import StrategyAJudge
from .strategy_b.judge_strategy_b import StrategyBJudge
from .strategy_c.judge_strategy_c import StrategyCJudge
from .strategy_d.judge_strategy_d import StrategyDJudge

__all__ = [
    "StrategyAJudge",
    "StrategyBJudge",
    "StrategyCJudge",
    "StrategyDJudge"
]

