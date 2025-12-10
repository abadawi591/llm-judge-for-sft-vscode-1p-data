# Strategy C: Text + Core Metrics + Tools

> **Input:** User message + core metrics (tokens, duration) + tool usage  
> **Cost:** ~$0.003 per classification  
> **Best For:** Full behavioral analysis with tool context

---

## Overview

Strategy C extends Strategy B by adding **tool usage information**. This provides the richest behavioral signal for classification.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY C: TEXT + CORE METRICS + TOOLS                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LLM Judge Input:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  User Message: "Fix the bug"                                         │    │
│  │                                                                       │    │
│  │  Core Metrics:                                                        │    │
│  │  ├── Prompt Tokens: 45,000                                           │    │
│  │  ├── Completion Tokens: 2,500                                        │    │
│  │  ├── LLM Calls: 5                                                    │    │
│  │  └── Duration: 48 seconds                                            │    │
│  │                                                                       │    │
│  │  Tool Usage:                                                          │    │
│  │  ├── Tools invoked: read_file, grep_search, edit_file, terminal     │    │
│  │  ├── Unique tools: 4                                                 │    │
│  │  ├── Total calls: 8                                                  │    │
│  │  └── Available: 78 tools                                             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  LLM Judge Output:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Label: 0 (Reasoning Required)                                       │    │
│  │  Confidence: 0.95                                                    │    │
│  │  Rationale: Complex tool chain (read→analyze→edit→verify)            │    │
│  │             indicates multi-step debugging process                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## What Strategy C Adds Over B

| Metric | Strategy B | Strategy C | Signal Value |
|--------|------------|------------|--------------|
| Prompt tokens | ✅ | ✅ | Context complexity |
| Completion tokens | ✅ | ✅ | Response length |
| LLM call count | ✅ | ✅ | Iteration count |
| Duration | ✅ | ✅ | Processing time |
| **Tools invoked** | ❌ | ✅ | **What tools were used** |
| **Unique tools** | ❌ | ✅ | **Task diversity** |
| **Total tool calls** | ❌ | ✅ | **Iteration depth** |
| **Available tools** | ❌ | ✅ | **Tool context** |

---

## Tool Usage Signals

### Strong Indicators of Reasoning (0)

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| Multiple different tools | `read_file, grep, edit, terminal` | Multi-step workflow |
| High tool call frequency | `read_file: 5, edit: 3` | Iterative refinement |
| Complex chains | `read → analyze → edit → verify` | Systematic debugging |

### Strong Indicators of Non-Reasoning (1)

| Pattern | Example | Interpretation |
|---------|---------|----------------|
| No tools | `none` | Simple answer |
| Single read | `read_file: 1` | Quick lookup |
| Only lookup tools | `grep_search: 1` | Finding information |

---

## Data Schema Compatibility

Strategy C works with the new nested schema:

```python
# New schema (recommended)
record = {
    "userMessage": "Fix the bug",
    "turnSummary": {
        "actual_API": {
            "maxPromptTokens_(system+user+assistant+toolResults)": 45000,
            "totalCompletionTokens": 2500
        },
        "llmCallCount": 5
    },
    "tools": {
        "definitions": {"count": 78},
        "invocations": {"withFrequency": '{"read_file": 3, "edit_file": 2}'}
    },
    "turnDurationMs": 48000
}

# Old flat schema (still supported)
record = {
    "userMessage": "Fix the bug",
    "promptTokens": 45000,
    "completionTokens": 2500,
    "llmCallCount": 5,
    "toolsUsed": ["read_file", "edit_file"],
    "durationMs": 48000
}
```

---

## When to Use Strategy C

| Use Case | Rationale |
|----------|-----------|
| ✅ **Full behavioral analysis** | Most complete signal |
| ✅ **Tool chain complexity matters** | Debugging, refactoring tasks |
| ✅ **Historical data with tools** | Post-hoc labeling |

---

## When NOT to Use Strategy C

| Scenario | Alternative |
|----------|-------------|
| ❌ Tool data unavailable | Use Strategy B |
| ❌ Real-time routing | Use Strategy A |
| ❌ Context history needed | Combine with Strategy D |

---

## Example Classifications

### Example 1: Complex Tool Chain → Reasoning (0)

```
User: "Fix the bug"

Core Metrics:
- Prompt tokens: 45,000
- Completion tokens: 2,500
- LLM calls: 5
- Duration: 48,000ms

Tool Usage:
- Tools: read_file (3x), grep_search (2x), edit_file (2x), terminal (1x)
- Unique: 4
- Total calls: 8

Output: 0 (Reasoning Required)
Confidence: 0.94
```

### Example 2: Simple Lookup → Non-Reasoning (1)

```
User: "What does this function do?"

Core Metrics:
- Prompt tokens: 5,000
- Completion tokens: 200
- LLM calls: 1
- Duration: 3,000ms

Tool Usage:
- Tools: read_file (1x)
- Unique: 1
- Total calls: 1

Output: 1 (Non-Reasoning Sufficient)
Confidence: 0.88
```

---

## Related Strategies

| Strategy | Input | When to Use |
|----------|-------|-------------|
| **A** | Text only | Baseline, real-time routing |
| **B** | Text + Core Metrics | When tool data not available |
| **C** | Text + Core + Tools | Full behavioral analysis |
| **D** | Text + History | Multi-turn context matters |

---

## Related

- [Strategy A](../strategy_a/STRATEGY_A.md) - Text only (baseline)
- [Strategy B](../strategy_b/STRATEGY_B.md) - Text + core metrics
- [Strategy D](../strategy_d/STRATEGY_D.md) - Text + conversation history
- [Voting Strategies](../../voting/VOTING_STRATEGIES.md) - Combining strategies
