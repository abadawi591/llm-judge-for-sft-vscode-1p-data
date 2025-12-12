# Strategy D: Text + Conversation History

> **Input:** User message + last N turns of conversation  
> **Cost:** ~$0.005 per classification  
> **Best For:** Multi-turn conversations, context-dependent requests

---

## Overview

Strategy D provides the LLM judge with **conversation history** to understand context-dependent complexity. This is essential for follow-up requests that reference prior work.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY D: TEXT + CONVERSATION HISTORY                  │
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

## When to Use Strategy D

| Use Case | Rationale |
|----------|-----------|
| ✅ **Multi-turn conversations** | Captures context-dependent complexity |
| ✅ **Follow-up requests** | "Now do X" makes sense with history |
| ✅ **Debugging requests** | Need to understand what was built |

---

## When NOT to Use Strategy D

| Scenario | Alternative |
|----------|-------------|
| ❌ Turn 1 (no history) | Use Strategy A or B |
| ❌ Cost-sensitive bulk labeling | Use Strategy A |
| ❌ Need behavioral metrics | Use Strategy B or C |

---

## Related Strategies

| Strategy | Input | When to Use |
|----------|-------|-------------|
| **A** | Text only | Baseline, real-time routing |
| **B** | Text + Core Metrics | Post-hoc labeling with token/duration data |
| **C** | Text + Core + Tools | When tool usage is important signal |
| **D** | Text + History | Multi-turn context matters |

---

## Related

- [Strategy A](../strategy_a/STRATEGY_A.md) - Text only (baseline)
- [Strategy B](../strategy_b/STRATEGY_B.md) - Text + core metrics
- [Strategy C](../strategy_c/STRATEGY_C.md) - Text + core + tools
- [Voting Strategies](../../voting/VOTING_STRATEGIES.md) - Combining strategies

