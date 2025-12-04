# Part 3: Data Balancing Strategies for SFT

This document covers strategies for creating balanced training datasets.

---

## 3.1 Target Dataset

- **Size:** ~100k balanced SFT samples
- **Balance ratios:** 50:50 or 70:30 (reasoning : non-reasoning)
- **Source:** Raw telemetry → Kusto queries → LLM-Judge annotation → Balance

---

## 3.2 Balancing Strategies

### Strategy 1: Stratified Sampling by Turn Count Buckets

```
Bucket A: 3-5 turns   (typical short tasks)    → N conversations
Bucket B: 6-10 turns  (medium complexity)      → N conversations  
Bucket C: 11-20 turns (complex multi-step)     → N conversations
```

| Pros | Cons |
|------|------|
| Equal representation | Arbitrary bucket boundaries |
| Easy to implement | May over/undersample natural patterns |

### Strategy 2: Complexity-Based Sampling

Balance by **task complexity signals** instead of turn count:

| Signal | Reasoning Proxy | Non-Reasoning Proxy |
|--------|-----------------|---------------------|
| `numRequests` | High (10+) | Low (1-2) |
| `turnDurationMs` | Long (>60s) | Short (<10s) |
| Tool diversity | Multiple tool types | Single/no tools |
| Token growth | High promptTokenDelta | Low promptTokenDelta |

### Strategy 3: Model-Based Pre-Stratification

Users choose models based on perceived task complexity. This is a **free signal**:

- Users who chose reasoning models → likely reasoning tasks
- Users who chose fast models → likely non-reasoning tasks

### Strategy 4: Inverse Frequency Weighting

```python
# If P(turnCount=3) = 0.30 and P(turnCount=15) = 0.01
weight[3] = 1/0.30 = 3.3
weight[15] = 1/0.01 = 100

# Rare turn counts get sampled more often
```

---

## 3.3 Recommended Pipeline: Session-Based Router

For ~100k final SFT samples:

```
┌─────────────────────────────────────────────────────────────────────┐
│  PIPELINE: SESSION-BASED ROUTER                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  STEP 1: Extract first turns from complete conversations             │
│  Query: sft_session_router_first_turns.kql                          │
│  Output: ~300k first-turn samples                                    │
│                                                                      │
│  STEP 2: Pre-stratify by complexity signals (optional)               │
│  - Split by model choice                                             │
│  - Split by numRequests (1 vs 2+ tool calls)                        │
│                                                                      │
│  STEP 3: LLM-Judge annotation                                        │
│  Input: userMessage (first turn)                                     │
│  Output: 0 (reasoning) or 1 (non-reasoning)                         │
│                                                                      │
│  STEP 4: Balance to target ratio                                     │
│  For 50:50: Sample 50k from each class                              │
│  For 70:30: Sample 70k reasoning, 30k non-reasoning                 │
│                                                                      │
│  OUTPUT: 100k balanced first-turn samples                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3.4 Recommended Pipeline: Conversation-Aware Router

```
┌─────────────────────────────────────────────────────────────────────┐
│  PIPELINE: CONVERSATION-AWARE ROUTER                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  STEP 1: Stratified sampling by turn count                           │
│  Query: sft_stratified_by_turn_count.kql                            │
│  Buckets: A (3-5), B (6-10), C (11-20) turns                        │
│  Output: ~25k conversations                                          │
│                                                                      │
│  STEP 2: Flatten to individual turns                                 │
│  Each turn becomes a training sample                                 │
│  Output: ~195k turns                                                 │
│                                                                      │
│  STEP 3: LLM-Judge annotation per turn                               │
│  Input: conversation history + current user message                  │
│  Output: 0 (reasoning) or 1 (non-reasoning)                         │
│                                                                      │
│  STEP 4: Balance by class AND turn position                          │
│  Ensure diversity in reasoning vs non-reasoning                      │
│  Ensure diversity in early/mid/late turns                           │
│                                                                      │
│  OUTPUT: 100k balanced turn samples                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3.5 Post-Query Balancing (Python)

```python
import pandas as pd

def balance_by_class(df, label_col='reasoning_label', target_ratio=0.5, total_samples=100000):
    """Balance dataset by reasoning/non-reasoning labels."""
    reasoning_df = df[df[label_col] == 0]
    non_reasoning_df = df[df[label_col] == 1]
    
    n_reasoning = int(total_samples * target_ratio)
    n_non_reasoning = total_samples - n_reasoning
    
    reasoning_sample = reasoning_df.sample(n=min(n_reasoning, len(reasoning_df)), 
                                           replace=len(reasoning_df) < n_reasoning)
    non_reasoning_sample = non_reasoning_df.sample(n=min(n_non_reasoning, len(non_reasoning_df)),
                                                    replace=len(non_reasoning_df) < n_non_reasoning)
    
    balanced = pd.concat([reasoning_sample, non_reasoning_sample]).sample(frac=1)
    return balanced
```

---

## Next: [04_QUERY_REFERENCE.md](04_QUERY_REFERENCE.md)

Continue to see all available Kusto queries.

