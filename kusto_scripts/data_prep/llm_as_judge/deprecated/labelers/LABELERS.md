# Labelers: Hard vs Soft Labels

This document explains the two types of labelers and when to use each.

---

## Overview

| Labeler | Output | Best For |
|---------|--------|----------|
| **HardLabeler** | Discrete: `0` or `1` | Classification, evaluation |
| **SoftLabeler** | Distribution: `[0.85, 0.15]` | SFT training, KD |

---

## Hard Labels

Hard labels are discrete classifications:
- `0` = Reasoning Required
- `1` = Non-Reasoning Sufficient

```python
from labelers import HardLabeler

labeler = HardLabeler(strategy="C")
result = labeler.label(record)

print(result.hard_label)    # 0 or 1
print(result.confidence)    # 0.92
```

### Use Cases
- ✅ Classification tasks
- ✅ Evaluation metrics (accuracy, F1)
- ✅ When you need definitive decisions
- ✅ Routing decisions

---

## Soft Labels

Soft labels are probability distributions over classes:
- `[p_reasoning, p_non_reasoning]` where sum = 1.0

```python
from labelers import SoftLabeler

labeler = SoftLabeler(strategy="C", method="confidence")
result = labeler.label(record)

print(result.soft_label)    # [0.85, 0.15]
print(result.p_reasoning)   # 0.85
print(result.p_non_reasoning)  # 0.15
```

### Use Cases
- ✅ **SFT Training** - Soft targets give smoother gradients
- ✅ **Knowledge Distillation** - Teacher provides soft targets for student
- ✅ **Ambiguous Cases** - Preserves uncertainty information
- ✅ **Ensemble Averaging** - Combine multiple judges smoothly

---

## Soft Label Methods

### 1. Confidence-Based (Default)

Converts the judge's confidence score to a probability distribution.

```python
labeler = SoftLabeler(strategy="C", method="confidence")
```

**How it works:**
```
Hard label: 0 (reasoning)
Confidence: 0.85

→ Soft label: [0.85, 0.15]
```

**Pros:** Fast (single LLM call)
**Cons:** Relies on judge's calibration

---

### 2. Temperature Scaling

Applies temperature to sharpen or soften the distribution.

```python
# Softer distribution (more uncertainty)
labeler = SoftLabeler(strategy="C", method="temperature", temperature=2.0)

# Sharper distribution (more confident)
labeler = SoftLabeler(strategy="C", method="temperature", temperature=0.5)
```

**Temperature effects:**
```
Original:    [0.85, 0.15]
temp=2.0:    [0.70, 0.30]  ← Softer
temp=0.5:    [0.95, 0.05]  ← Sharper
```

---

### 3. Multi-Run Averaging

Runs the judge N times and averages the results.

```python
labeler = SoftLabeler(strategy="C", method="multi_run", n_runs=3)
```

**How it works:**
```
Run 1: [0.90, 0.10]
Run 2: [0.75, 0.25]
Run 3: [0.85, 0.15]
─────────────────────
Average: [0.83, 0.17]
```

**Pros:** More robust, captures LLM variance
**Cons:** 3x slower, 3x cost

---

### 4. Ensemble Averaging

Averages across multiple strategies.

```python
labeler = SoftLabeler(
    method="ensemble",
    ensemble_strategies=["B", "C", "D"]
)
```

**How it works:**
```
Strategy B: [0.80, 0.20]
Strategy C: [0.90, 0.10]
Strategy D: [0.75, 0.25]
─────────────────────
Average: [0.82, 0.18]
```

**Pros:** Most robust, diverse perspectives
**Cons:** Slowest, highest cost

---

## Knowledge Distillation Pattern

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE DISTILLATION WORKFLOW                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ TEACHER: LLM Judge (Claude Sonnet 4.5)                               │    │
│  │                                                                       │    │
│  │ Input: Turn data + Strategy C (full context)                        │    │
│  │ Output: Soft labels [0.85, 0.15]                                    │    │
│  │                                                                       │    │
│  │ SoftLabeler(strategy="C", method="ensemble")                        │    │
│  └───────────────────────────┬─────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼ Soft targets                                  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ STUDENT: Lightweight Classifier (ModernBERT, DistilBERT)            │    │
│  │                                                                       │    │
│  │ Input: Text only (Strategy A format)                                │    │
│  │ Output: Predicted probabilities                                      │    │
│  │                                                                       │    │
│  │ Loss = KL_divergence(student_probs, teacher_soft_labels)           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  BENEFITS:                                                                   │
│  ├── Student learns from teacher's uncertainty                              │
│  ├── Smoother gradients than hard labels                                    │
│  ├── Better generalization                                                   │
│  └── Can deploy lightweight student model for real-time routing            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SFT with Soft Labels

For SFT training, use `to_sft_format()`:

```python
result = soft_labeler.label(record)
sft_data = result.to_sft_format()

# sft_data = {
#     "label_distribution": [0.85, 0.15],
#     "temperature": 1.0
# }
```

### Training with Soft Labels

```python
import torch.nn.functional as F

# Hard label training (CE loss)
loss = F.cross_entropy(logits, hard_labels)

# Soft label training (KL divergence)
soft_targets = torch.tensor(result.soft_label)
log_probs = F.log_softmax(logits, dim=-1)
loss = F.kl_div(log_probs, soft_targets, reduction='batchmean')
```

---

## Choosing the Right Labeler

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DECISION FLOWCHART                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  What's your use case?                                                       │
│  │                                                                           │
│  ├─► Classification / Evaluation                                            │
│  │   └─► Use HardLabeler                                                    │
│  │                                                                           │
│  ├─► SFT Training                                                           │
│  │   └─► Use SoftLabeler (method="confidence" or "ensemble")               │
│  │                                                                           │
│  ├─► Knowledge Distillation                                                 │
│  │   └─► Use SoftLabeler (method="ensemble" for teacher)                   │
│  │                                                                           │
│  └─► Handling Ambiguous Cases                                               │
│      └─► Use SoftLabeler (method="multi_run" or "ensemble")                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Cost Comparison

| Method | LLM Calls per Record | Cost Factor |
|--------|---------------------|-------------|
| Hard label | 1 | 1x |
| Soft (confidence) | 1 | 1x |
| Soft (multi_run, n=3) | 3 | 3x |
| Soft (ensemble, 3 strategies) | 3 | 3x |

---

## Example: Full Workflow

```python
import asyncio
from labelers import SoftLabeler, HardLabeler

# 1. Generate soft labels for SFT training
soft_labeler = SoftLabeler(
    strategy="C",
    method="ensemble",
    ensemble_strategies=["B", "C", "D"]
)

# 2. Label dataset
records = [...]  # Your turn data
results = asyncio.run(soft_labeler.label_batch_async(records))

# 3. Prepare SFT data
sft_data = []
for record, result in zip(records, results):
    sft_data.append({
        "input": record["userMessage"],
        "soft_label": result.soft_label,
        "hard_label": result.hard_label,
        "confidence": result.confidence
    })

# 4. Save for training
import json
with open("sft_soft_labels.jsonl", "w") as f:
    for item in sft_data:
        f.write(json.dumps(item) + "\n")
```

---

## Related

- [Strategy A](../strategies/strategy_a/STRATEGY_A.md)
- [Strategy B](../strategies/strategy_b/STRATEGY_B.md)
- [Strategy C](../strategies/strategy_c/STRATEGY_C.md)
- [Strategy D](../strategies/strategy_d/STRATEGY_D.md)
- [Voting Strategies](../voting/VOTING_STRATEGIES.md)

