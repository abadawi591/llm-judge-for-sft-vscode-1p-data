# Part 2: Routing Strategies

This document explains the two routing architectures for model selection.

---

## 2.1 Project Goal

Train a **BERT classifier** to route user messages between:

| Label | Model Type | When to Use |
|-------|------------|-------------|
| **0** | Reasoning | Complex tasks requiring deep thinking |
| **1** | Non-reasoning | Simple tasks, quick responses |

**Target:** 100k balanced SFT samples.

---

## 2.2 Two Router Architectures

| Router Type | Training Unit | What Gets Classified | Turn Count Impact |
|-------------|---------------|---------------------|-------------------|
| **Session-based** | First turn only | Route entire conversation at start | Low - 10-turn convo = 1 sample |
| **Conversation-aware** | Every turn | Re-route at each turn | High - 10-turn convo = 10 samples |

---

## 2.3 Session-Based Routing

### Concept

Routing decision is made **once per conversation**, based on `turnIndex = 1` (the first user message).

<!-- DIAGRAM PLACEHOLDER: session_routing_flow.svg -->

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SESSION-BASED ROUTING                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User sends first message (turnIndex = 1)                          │
│                     │                                               │
│                     ▼                                               │
│   ┌─────────────────────────────────────┐                          │
│   │  BERT Classifier (fine-tuned)       │                          │
│   │  Input: userMessage                 │                          │
│   │  Output: 0 (reasoning) or 1 (fast)  │                          │
│   └─────────────────────────────────────┘                          │
│                     │                                               │
│         ┌───────────┴───────────┐                                  │
│         ▼                       ▼                                   │
│   ┌───────────┐          ┌───────────┐                             │
│   │ Reasoning │          │ Non-reason│                             │
│   │ Model     │          │ Model     │                             │
│   └───────────┘          └───────────┘                             │
│         │                       │                                   │
│         └───────────┬───────────┘                                  │
│                     ▼                                               │
│   ┌─────────────────────────────────────┐                          │
│   │  Same model for ALL subsequent      │                          │
│   │  turns in this conversation         │                          │
│   │  (turnIndex = 2, 3, 4, ...)         │                          │
│   │                                     │                          │
│   │  NO re-routing within conversation  │                          │
│   └─────────────────────────────────────┘                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Characteristics

- **One-time decision** at conversation start
- **No switching** - model remains constant throughout conversation
- **Simple** - just classify the first message
- **Fast** - no overhead for subsequent turns

### Data Collection

For session-based routing, we only need first turns:

```kql
| where turnIndex == 1  // Only first messages
```

Each conversation contributes **1 training sample** regardless of length.

---

## 2.4 Conversation-Aware Routing

### Concept

Routing decision is made **at every turn**, considering conversation context.

```
┌─────────────────────────────────────────────────────────────────────┐
│                CONVERSATION-AWARE ROUTING                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Turn 1: "Fix the bug in login.py"                                 │
│          │                                                          │
│          ▼  Classifier → 0 (reasoning) → Opus handles              │
│                                                                     │
│  Turn 2: "Now add a comment to that function"                      │
│          │                                                          │
│          ▼  Classifier → 1 (non-reasoning) → Sonnet handles        │
│                                                                     │
│  Turn 3: "Actually, refactor the whole auth module"                │
│          │                                                          │
│          ▼  Classifier → 0 (reasoning) → Opus handles              │
│                                                                     │
│  Re-routing at each turn based on current request complexity        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Characteristics

- **Per-turn decision** based on current message + context
- **Can switch models** mid-conversation
- **More complex** - needs conversation history
- **More accurate** - adapts to changing task complexity

### Data Collection

For conversation-aware routing, we need all turns:

Each turn becomes a training sample. A 10-turn conversation contributes **10 training samples**.

---

## 2.5 Training Data Requirements

### Session-Based Router

| Field | Purpose |
|-------|---------|
| `userMessage` (turnIndex = 1) | Input to classifier |
| Conversation metadata | Context signals |

**Query:** [production/sft_session_router_first_turns.kql](../production/sft_session_router_first_turns.kql)

### Conversation-Aware Router

| Field | Purpose |
|-------|---------|
| `userMessage` (any turn) | Input to classifier |
| Previous turns | Context for decision |
| `turnIndex` | Position in conversation |

**Query:** [production/sft_stratified_by_turn_count.kql](../production/sft_stratified_by_turn_count.kql)

---

## 2.6 Model Switching Patterns (Discovery)

Users can manually switch models mid-conversation. This is **valuable data for conversation-aware routing**.

### Distribution (Verified 2025-12-03)

| Models Used | Conversations | Percentage |
|-------------|---------------|------------|
| **1** | **46,806** | **95.8%** |
| 2 | 1,845 | 3.8% |
| 3+ | 227 | 0.4% |

**Key insight:** ~96% of conversations use a single model. Model switching is rare but informative.

### Common Switch Patterns

| Pattern | Example | Likely Reason |
|---------|---------|---------------|
| **Upgrade** | Sonnet → Opus | Task became too complex |
| **Downgrade** | Opus → Sonnet | Task simpler, save cost/time |
| **Provider switch** | GPT-4o → Claude | User preference |

---

## Next: [03_DATA_BALANCING.md](03_DATA_BALANCING.md)

Continue to learn about balancing strategies for SFT training data.

