# Strategy C: Text + Conversation History (RECOMMENDED)

> **Input:** User message + last N turns of conversation  
> **Cost:** ~$0.005 per classification  
> **Best For:** Multi-turn conversations, production labeling

---

## Overview

Strategy C is the **recommended approach** for labeling multi-turn Copilot Agent Mode conversations. It provides the LLM judge with conversation history to understand context-dependent complexity.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY C: TEXT + CONVERSATION HISTORY                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LLM Judge Input:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  CONVERSATION HISTORY (last 3 turns):                                │    │
│  │                                                                       │    │
│  │  [Turn 5] User: "Add user authentication to the API"                 │    │
│  │           Assistant: "I'll add JWT-based auth..." [truncated]        │    │
│  │                                                                       │    │
│  │  [Turn 6] User: "Now add refresh tokens"                             │    │
│  │           Assistant: "I've implemented refresh..." [truncated]       │    │
│  │                                                                       │    │
│  │  [Turn 7] User: "Also handle token expiration gracefully"            │    │
│  │           Assistant: "I've added automatic..." [truncated]           │    │
│  │                                                                       │    │
│  │  ─────────────────────────────────────────────────────────────────   │    │
│  │                                                                       │    │
│  │  CURRENT REQUEST (Turn 8):                                            │    │
│  │  "Fix the bug in the token validation"                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  LLM Judge Output:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Label: 0 (Reasoning Required)                                       │    │
│  │  Confidence: 0.91                                                    │    │
│  │  Rationale: Request builds on complex auth system established        │    │
│  │             over 3 turns; debugging requires understanding context   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Why Strategy C is Recommended

### The Context Problem

Without history, many requests are **ambiguous**:

| Request | Without History | With History |
|---------|-----------------|--------------|
| "Fix the bug" | Unknown → 0.5 confidence | Turn 8 of complex auth → 0 with 0.95 confidence |
| "Now add tests" | Simple → 1 | After modifying 12 files → 0 |
| "Make it work" | Vague → 0.5 | Reference to specific prior discussion → clear |

### What Changed with History

```
BEFORE (Strategy A):                    AFTER (Strategy C):
                                       
"Fix the bug"                          [Turn 5] User: Add authentication...
   ↓                                   [Turn 6] User: Add refresh tokens...
Label: ? (ambiguous)                   [Turn 7] User: Handle expiration...
Confidence: 0.55                       [Turn 8] User: "Fix the bug"
                                           ↓
                                       Label: 0 (debugging complex auth)
                                       Confidence: 0.91
```

---

## Context Window Strategy

### How Many Turns to Include?

| Conversation Length | Turns to Include | Rationale |
|--------------------|------------------|-----------|
| 1-3 turns (short) | All previous turns | Small enough to include everything |
| 4-10 turns (medium) | Last 5 turns | Recent context most relevant |
| 11+ turns (long) | Turn 1 + last 4 turns | Initial context + recent history |

### Implementation

```python
def get_context_window(turns: list, current_idx: int) -> list:
    """Select which turns to include in context."""
    
    if current_idx <= 3:
        # Short conversation: include all previous turns
        return turns[:current_idx]
    
    elif current_idx <= 10:
        # Medium: last 5 turns
        start = max(0, current_idx - 5)
        return turns[start:current_idx]
    
    else:
        # Long: turn 1 + last 4 turns
        return [turns[0]] + turns[current_idx - 4:current_idx]
```

---

## When to Use Strategy C

| Use Case | Rationale |
|----------|-----------|
| ✅ **Multi-turn conversations** | Captures context-dependent complexity |
| ✅ **Agent mode sessions** | Typical sessions have 5-15 turns |
| ✅ **Production labeling** | Best accuracy for generating training data |
| ✅ **Follow-up requests** | "Now do X" makes sense with history |

---

## When NOT to Use Strategy C

| Scenario | Alternative |
|----------|-------------|
| ❌ Turn 1 (no history) | Use Strategy A |
| ❌ Cost-sensitive bulk labeling | Use Strategy A, sample with C |
| ❌ Real-time routing with 8k limit | Train on C labels, route with A |

---

## Prompt Template

```
You are classifying whether the CURRENT user request requires a reasoning-capable LLM.
Consider the conversation history to understand context.

═══════════════════════════════════════════════════════════════════════════
CONVERSATION METADATA
═══════════════════════════════════════════════════════════════════════════
- Total turns in conversation: {total_turns}
- Current turn: {current_turn_index}

═══════════════════════════════════════════════════════════════════════════
CONVERSATION HISTORY (last {n_context} turns)
═══════════════════════════════════════════════════════════════════════════
{formatted_history}

═══════════════════════════════════════════════════════════════════════════
CURRENT REQUEST (Turn {current_turn_index})
═══════════════════════════════════════════════════════════════════════════
User: {current_user_message}

CLASSIFICATION GUIDELINES:

Consider these factors:
1. Does this request BUILD on previous context in complex ways?
2. Would a model WITHOUT this history misunderstand the request?
3. Is there accumulated state (files modified, decisions made)?
4. Is this a simple follow-up or a new complex direction?

REASONING REQUIRED (0):
- Builds on complex prior work
- References previous decisions/changes
- Debugging issues introduced earlier
- Continuing multi-step implementation

NON-REASONING SUFFICIENT (1):
- Independent of prior context
- Simple follow-up ("yes", "sounds good")
- New topic unrelated to history
- Basic clarifying questions

OUTPUT FORMAT (exactly two lines):
Line 1: Label (0 or 1)
Line 2: Confidence (decimal between 0.0 and 1.0)
```

---

## Example Classifications

### Example 1: Context-Dependent Debugging

**Conversation History:**
```
[Turn 5] User: "Add user authentication to the API"
         Assistant: "I'll implement JWT-based auth..." (implemented 3 files)

[Turn 6] User: "Now add refresh tokens"
         Assistant: "I've added refresh token logic..." (modified 2 files)

[Turn 7] User: "Handle token expiration gracefully"
         Assistant: "I've implemented automatic..." (modified 4 files)
```

**Current Request (Turn 8):**
```
User: "Fix the bug in the token validation"
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.91,
  "reasoning": "Debugging builds on 3 turns of complex auth implementation. Understanding the token flow requires context from previous turns."
}
```

### Example 2: Independent Follow-up

**Conversation History:**
```
[Turn 3] User: "Create a new React component for the sidebar"
         Assistant: "I've created the Sidebar component..."

[Turn 4] User: "Add some CSS styling to it"
         Assistant: "I've added styling..."
```

**Current Request (Turn 5):**
```
User: "What's the syntax for CSS flexbox?"
```

**Output:**
```json
{
  "label": 1,
  "confidence": 0.88,
  "reasoning": "Simple factual question that doesn't depend on the specific implementation context. Standard syntax inquiry."
}
```

### Example 3: Escalating Complexity

**Conversation History:**
```
[Turn 1] User: "Help me build a simple todo app"
         Assistant: "I'll create a basic todo app..."

[Turn 2] User: "Add the ability to set due dates"
         Assistant: "I've added date picker..."

[Turn 3] User: "Now add recurring todos that repeat weekly/monthly"
         Assistant: "I've implemented recurring..."
```

**Current Request (Turn 4):**
```
User: "The recurring todos aren't syncing correctly across devices"
```

**Output:**
```json
{
  "label": 0,
  "confidence": 0.94,
  "reasoning": "Debugging cross-device sync issue requires understanding the recurring todo implementation from Turn 3 and potential state management assumptions."
}
```

---

## Handling Long Responses

Assistant responses can be very long (thousands of tokens). Use truncation:

```python
def format_turn_for_context(turn: dict, max_response_len: int = 500) -> str:
    """Format a turn for inclusion in context."""
    
    user_msg = turn["userMessage"]
    assistant_msg = turn["modelMessage"]
    
    # Truncate long responses
    if len(assistant_msg) > max_response_len:
        assistant_msg = assistant_msg[:max_response_len] + "... [truncated]"
    
    return f"""[Turn {turn['turnIndex']}]
User: {user_msg}
Assistant: {assistant_msg}
"""
```

---

## Token Budget Analysis

For ModernBERT's 8k context (if using C for training):

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | ~300 | Fixed |
| Metadata | ~50 | Turn count, current index |
| 5 turns × 300 avg | ~1500 | With truncation |
| Current message | ~150 | Average |
| **Total** | **~2000** | Fits comfortably |

For labeling with Claude (200k context): no practical limit.

---

## Comparison: Strategy A vs C

| Metric | Strategy A | Strategy C |
|--------|------------|------------|
| **Accuracy** | Baseline | +15-25% on multi-turn |
| **Cost** | $0.001 | $0.005 |
| **Context** | None | Last 5 turns |
| **Ambiguity handling** | Poor | Good |
| **Turn 1 performance** | Same | Same |
| **Follow-up detection** | Poor | Good |

---

## Implementation Notes

### First Turn Fallback

```python
def classify(self, record: dict) -> ClassificationResult:
    turn_index = record.get("turnIndex", 0)
    
    if turn_index == 0:
        # No history for first turn, use Strategy A
        return self.strategy_a.classify(record["userMessage"])
    
    # Use Strategy C with history
    return self._classify_with_history(record)
```

### Caching Turn Data

For efficiency, preload conversation data:

```python
def load_conversation_cache(conversations: list) -> dict:
    """Build a cache of conversations indexed by ID."""
    return {c["conversationId"]: c["turnsArray"] for c in conversations}
```

---

## Cost Analysis

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt | ~300 | — |
| History (5 turns × 300) | ~1500 | — |
| Current message | ~150 | — |
| Output | ~5 | — |
| **Total per call** | ~1955 | **~$0.005** |

For 600k turns: **~$450-500 total**

---

## Related

- [Strategy A](../strategy_a/STRATEGY_A.md) - Text only (baseline)
- [Strategy B](../strategy_b/STRATEGY_B.md) - Text + behavioral metrics
- [Voting Strategies](../../voting/VOTING_STRATEGIES.md) - Combining strategies

