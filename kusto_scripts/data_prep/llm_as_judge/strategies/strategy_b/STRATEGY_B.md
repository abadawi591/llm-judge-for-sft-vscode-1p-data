# Strategy B: Text + Core Metrics

> **Input:** User message + core telemetry (tokens, duration, LLM calls)  
> **Cost:** ~$0.002 per classification  
> **Best For:** Post-hoc labeling when tool data is not needed

---

## Overview

Strategy B enriches the classification with **observed behavioral signals**—what actually happened when the LLM processed the request. This includes token counts, tool usage, and processing time.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY B: TEXT + BEHAVIORAL METRICS                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LLM Judge Input:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  User Message: "Fix the bug"                                         │    │
│  │                                                                       │    │
│  │  Observed Behavior:                                                   │    │
│  │  ├── Prompt Tokens: 45,000                                           │    │
│  │  ├── Completion Tokens: 2,500                                        │    │
│  │  ├── LLM Calls: 5                                                    │    │
│  │  ├── Tools Used: read_file, grep, edit_file, terminal                │    │
│  │  └── Duration: 45 seconds                                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  LLM Judge Output:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Label: 0 (Reasoning Required)                                       │    │
│  │  Confidence: 0.92                                                    │    │
│  │  Rationale: High token usage and multi-step tool chain indicate      │    │
│  │             complex debugging despite simple request text            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Insight: Hindsight Labels

⚠️ **Important:** Strategy B uses **hindsight information** that is only available AFTER the LLM response. This means:

- ✅ **Great for labeling** - Uses ground truth about what happened
- ❌ **Not for deployment** - Router can't see these metrics at inference time

This is intentional: we use the best available information to generate high-quality labels, then train a simpler router on limited input.

---

## Behavioral Signals

### Available Metrics

| Signal | Source | Interpretation |
|--------|--------|----------------|
| `promptTokens` | Telemetry | High = accumulated context, likely complex |
| `completionTokens` | Telemetry | High + multi-call = reasoning needed |
| `llmCallCount` | Telemetry | >2 calls often indicates tool use loop |
| `toolsUsed` | Telemetry | Complex tool chains = reasoning |
| `durationMs` | Telemetry | Longer = more complex processing |

### Interpretation Guidelines

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SIGNAL INTERPRETATION                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STRONG INDICATORS OF REASONING (0):                                        │
│  ├── completionTokens > 1500 AND llmCalls > 2                               │
│  ├── Tool chain: read → analyze → edit → verify                            │
│  ├── Duration > 45 seconds                                                  │
│  └── High promptTokens (>40k) indicates accumulated complexity              │
│                                                                              │
│  STRONG INDICATORS OF NON-REASONING (1):                                    │
│  ├── completionTokens < 300 AND llmCalls == 1                               │
│  ├── No tools or single read_file                                           │
│  ├── Duration < 5 seconds                                                   │
│  └── Low promptTokens (<5k) on turn 1                                       │
│                                                                              │
│  OVER-COMPLICATED DETECTION:                                                 │
│  ├── Simple request + excessive behavior → Consider 1                       │
│  └── "What is X?" + 5 LLM calls = Model over-thought it                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## When to Use Strategy B

| Use Case | Rationale |
|----------|-----------|
| ✅ **Historical data labeling** | Telemetry already captured behavior |
| ✅ **Detecting over-complication** | Spot when model does too much |
| ✅ **Ground-truth validation** | Verify labels against actual behavior |
| ✅ **Ambiguous requests** | "Fix it" becomes clear with metrics |

---

## When NOT to Use Strategy B

| Scenario | Problem |
|----------|---------|
| ❌ Real-time routing | Metrics not available at inference time |
| ❌ Training router directly | Router can't use these signals |
| ❌ When telemetry is incomplete | Missing data leads to bad labels |

---

## Prompt Template

```
You are classifying whether a user request required a reasoning-capable LLM.
You have access to both the request AND what actually happened when it was processed.

USER REQUEST:
{user_message}

OBSERVED BEHAVIOR (what the LLM actually did):
- Prompt tokens used: {prompt_tokens}
- Completion tokens generated: {completion_tokens}
- Number of LLM calls: {llm_call_count}
- Tools invoked: {tool_list}
- Total tool calls: {total_tool_calls}
- Processing duration: {duration_ms}ms

CLASSIFICATION GUIDELINES:

REASONING REQUIRED (0):
- High completion tokens (>1500) with multiple LLM calls (>2)
- Complex tool chains (file reads → analysis → edits → terminal)
- Long processing duration (>30 seconds)
- High prompt tokens (>40k) indicating accumulated context

NON-REASONING SUFFICIENT (1):
- Low completion tokens (<500) with single LLM call
- Simple or no tool usage
- Quick response (<10 seconds)
- Request complexity matches (or exceeds) observed behavior

OVER-COMPLICATION CHECK:
- If behavior seems EXCESSIVE for the request, lean toward 1
- Simple question + complex behavior = model over-thought it

OUTPUT FORMAT (exactly two lines):
Line 1: Label (0 or 1)
Line 2: Confidence (decimal between 0.0 and 1.0)
```

---

## Example Classifications

### Example 1: Simple Request, Complex Behavior → Reasoning (0)

**Input:**
```
User: "Fix the bug"

Observed Behavior:
- Prompt tokens: 45,000
- Completion tokens: 2,500
- LLM calls: 5
- Tools: read_file (3x), grep_search (2x), edit_file (2x), terminal (1x)
- Duration: 48,000ms
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.94,
  "reasoning": "Despite simple request, behavior shows complex multi-file debugging with verification loop"
}
```

### Example 2: Complex Request, Simple Behavior → Non-Reasoning (1)

**Input:**
```
User: "Implement a full OAuth2 authentication flow with refresh tokens and session management"

Observed Behavior:
- Prompt tokens: 3,500
- Completion tokens: 150
- LLM calls: 1
- Tools: none
- Duration: 2,000ms
```

**Output:**
```json
{
  "label": 1,
  "confidence": 0.82,
  "reasoning": "Complex request but minimal behavior suggests model declined or gave simple answer"
}
```

### Example 3: Matched Complexity → Reasoning (0)

**Input:**
```
User: "Debug why the authentication middleware is rejecting valid tokens"

Observed Behavior:
- Prompt tokens: 28,000
- Completion tokens: 1,800
- LLM calls: 4
- Tools: read_file (2x), grep_search (3x), edit_file (1x)
- Duration: 35,000ms
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.96,
  "reasoning": "Request complexity matches observed behavior - genuine debugging task"
}
```

---

## Edge Cases

### Over-Complication Detection

```
User: "What is a Python decorator?"

Observed:
- 3 LLM calls
- 1,200 completion tokens
- read_file calls

Label: 1 (Non-reasoning)
Confidence: 0.75
Reason: Simple factual question, model over-complicated response
```

### Incomplete Telemetry

```
User: "Refactor the database layer"

Observed:
- Prompt tokens: 0 (missing)
- Completion tokens: 0 (missing)
- LLM calls: null

Label: Defer to Strategy A or C
Confidence: N/A
Reason: Cannot use Strategy B without telemetry
```

---

## Implementation Notes

### Handling Missing Data

```python
def has_valid_telemetry(record: dict) -> bool:
    """Check if record has sufficient telemetry for Strategy B."""
    return (
        record.get("promptTokens", 0) > 0 and
        record.get("completionTokens", 0) > 0 and
        record.get("llmCallCount") is not None
    )
```

### Fallback Strategy

```python
if has_valid_telemetry(record):
    result = strategy_b.classify(record)
else:
    result = strategy_a.classify(record["userMessage"])
```

---

## Cost Analysis

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt | ~200 | — |
| User message (avg) | ~150 | — |
| Behavioral metrics | ~100 | — |
| Output | ~5 | — |
| **Total per call** | ~455 | **~$0.002** |

For 600k turns: **~$180 total**

---

## Related

- [Strategy A](../strategy_a/STRATEGY_A.md) - Text only (baseline)
- [Strategy C](../strategy_c/STRATEGY_C.md) - Text + history
- [Voting Strategies](../../voting/VOTING_STRATEGIES.md) - Combining strategies

