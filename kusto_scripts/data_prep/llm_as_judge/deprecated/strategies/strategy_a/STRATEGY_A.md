# Strategy A: Text Only (Baseline)

> **Input:** Current user message only  
> **Cost:** ~$0.001 per classification  
> **Best For:** Deployment-time inference, baseline comparison

---

## Overview

Strategy A is the **simplest and cheapest** approach. The LLM judge sees ONLY the current user message—no conversation history, no behavioral metrics.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STRATEGY A: TEXT ONLY                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LLM Judge Input:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  User Message: "Fix the authentication bug in the login flow"       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  LLM Judge Output:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Label: 0 (Reasoning Required)                                      │    │
│  │  Confidence: 0.85                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## When to Use Strategy A

| Use Case | Rationale |
|----------|-----------|
| ✅ **Deployment-time routing** | Matches what router will see at inference |
| ✅ **Baseline comparison** | Measure value of additional context |
| ✅ **First-turn classification** | No history exists yet |
| ✅ **Cost-sensitive labeling** | 5x cheaper than Strategy C |

---

## When NOT to Use Strategy A

| Scenario | Problem |
|----------|---------|
| ❌ Multi-turn conversations | "Fix it" is ambiguous without context |
| ❌ Follow-up questions | Loses all accumulated state |
| ❌ Complex debugging sessions | Can't see prior attempts |

---

## Prompt Template

```
You are classifying whether a user request requires a reasoning-capable LLM.

USER REQUEST:
{user_message}

CLASSIFICATION GUIDELINES:

REASONING REQUIRED (0):
- Complex multi-step problems
- Debugging, refactoring, architectural decisions
- Ambiguous requests needing interpretation
- Requests involving code generation or analysis
- "Why" questions or root cause analysis

NON-REASONING SUFFICIENT (1):
- Simple, direct questions
- Straightforward lookups or explanations
- Single-file, obvious edits
- Yes/no questions with clear answers
- Simple formatting or style changes

OUTPUT FORMAT:
First line: Label (0 or 1)
Second line: Confidence (0.0 to 1.0)

Example output:
0
0.85
```

---

## Example Classifications

### Example 1: Clear Reasoning (0)

**Input:**
```
User: Refactor this module to use the repository pattern, ensure all 
existing tests pass, and update the dependency injection configuration.
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.95,
  "reasoning": "Multi-step task involving architectural pattern, testing, and configuration"
}
```

### Example 2: Clear Non-Reasoning (1)

**Input:**
```
User: What is the syntax for a Python list comprehension?
```

**Output:**
```json
{
  "label": 1,
  "confidence": 0.98,
  "reasoning": "Simple factual question with a direct answer"
}
```

### Example 3: Ambiguous (Low Confidence)

**Input:**
```
User: Fix the bug
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.55,
  "reasoning": "Ambiguous - could be trivial or complex depending on context"
}
```

---

## Limitations

### 1. Context Blindness

Strategy A cannot distinguish between:

```
Turn 1: "Fix the bug"           → Could be simple typo
Turn 7: "Fix the bug"           → After 6 turns of complex debugging, likely complex
```

Both will receive the same classification despite vastly different contexts.

### 2. Follow-up Misclassification

```
Turn 5: "Now make it work with OAuth2"

Without history: Sounds like a fresh OAuth2 request → 0
With history: 5th iteration of the same login system → 0 with higher confidence
```

### 3. Accumulated Complexity Invisible

```
After modifying 15 files across 8 turns:
"Clean up the imports"

Without context: Sounds simple → 1
With context: Complex due to accumulated state → 0
```

---

## Implementation Notes

### Prompt Optimization

Keep the prompt short to minimize costs:

```python
# Short version (~100 tokens)
PROMPT_SHORT = """Classify: 0=reasoning required, 1=non-reasoning sufficient

Request: {user_message}

Output: [label] [confidence]"""
```

### Confidence Calibration

Strategy A tends to have **lower confidence** on ambiguous requests. Use this signal:

```python
if confidence < 0.6:
    # Consider escalating to Strategy C for verification
    pass
```

### Deployment Alignment

Strategy A's labels align with what a deployed router would produce, making it ideal for:

1. **Train/test consistency**: Router sees same input at inference as during training
2. **Error analysis**: Easy to understand why router made a decision
3. **A/B testing**: Compare router performance against Strategy A baseline

---

## Cost Analysis

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt | ~100 | — |
| User message (avg) | ~150 | — |
| Output | ~5 | — |
| **Total per call** | ~255 | **~$0.001** |

For 600k turns: **~$100 total**

---

## Related

- [Strategy B](../strategy_b/STRATEGY_B.md) - Adds behavioral metrics
- [Strategy C](../strategy_c/STRATEGY_C.md) - Adds conversation history
- [Voting Strategies](../../voting/VOTING_STRATEGIES.md) - Combining multiple strategies

