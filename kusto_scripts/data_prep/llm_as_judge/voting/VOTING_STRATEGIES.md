# Multi-Judge Voting Strategies

> **Goal:** Improve label quality and reliability by combining multiple LLM judge decisions.

---

## Overview

Voting combines classifications from multiple judges (strategies, models, or runs) to produce more reliable labels. This is especially valuable for:

- **Ambiguous cases** where a single judge has low confidence
- **High-stakes labeling** where errors are costly
- **Gold-standard datasets** for evaluation

---

## Voting Strategies

### 1. Strategy Voting (A vs B vs C)

Combine votes from different labeling strategies, each with different inputs.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STRATEGY VOTING (A + B + C)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Same Model, Different Inputs:                                              │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ STRATEGY A       │  │ STRATEGY B       │  │ STRATEGY C       │          │
│  │ (Text Only)      │  │ (Text + Metrics) │  │ (Text + History) │          │
│  │                  │  │                  │  │                  │          │
│  │ Input:           │  │ Input:           │  │ Input:           │          │
│  │ User message     │  │ User message     │  │ User message     │          │
│  │                  │  │ + Token counts   │  │ + Last 5 turns   │          │
│  │                  │  │ + Tool usage     │  │                  │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                     │                     │
│           ▼                     ▼                     ▼                     │
│       Label: 0              Label: 0              Label: 0                  │
│       Conf: 0.72            Conf: 0.91            Conf: 0.88                │
│           │                     │                     │                     │
│           └─────────────────────┼─────────────────────┘                     │
│                                 ▼                                           │
│                    ┌────────────────────────┐                               │
│                    │    VOTING LOGIC        │                               │
│                    │    Weighted: 0.2A +    │                               │
│                    │              0.3B +    │                               │
│                    │              0.5C      │                               │
│                    └────────────┬───────────┘                               │
│                                 ▼                                           │
│                    ┌────────────────────────┐                               │
│                    │  FINAL: Label 0        │                               │
│                    │  Confidence: 0.87      │                               │
│                    │  Agreement: 3/3        │                               │
│                    └────────────────────────┘                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Leverages complementary information
- ✅ Strategy B catches over-complication
- ✅ Strategy C provides context
- ✅ Disagreement signals ambiguity

**Cons:**
- ❌ 3x cost
- ❌ Only works for labeling (B uses hindsight)

**Recommended Weights:**
| Strategy | Weight | Rationale |
|----------|--------|-----------|
| A | 0.20 | Baseline, least information |
| B | 0.30 | Ground-truth behavioral signals |
| C | 0.50 | Best accuracy, recommended primary |

---

### 2. Model Voting (Same Strategy, Different Models)

Use the same input strategy but different LLM models as judges.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     MODEL VOTING (Claude vs GPT vs Gemini)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Same Input (Strategy C), Different Models:                                 │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Claude Sonnet    │  │ GPT-4o           │  │ Gemini 1.5       │          │
│  │ 4.5              │  │                  │  │ Pro              │          │
│  │                  │  │                  │  │                  │          │
│  │ Label: 0         │  │ Label: 0         │  │ Label: 1         │          │
│  │ Conf: 0.88       │  │ Conf: 0.85       │  │ Conf: 0.72       │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                     │                     │
│           └─────────────────────┼─────────────────────┘                     │
│                                 ▼                                           │
│                    ┌────────────────────────┐                               │
│                    │    MAJORITY VOTE       │                               │
│                    │    2 vs 1 → Label 0    │                               │
│                    └────────────────────────┘                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Reduces single-model bias
- ✅ Higher reliability for ambiguous cases
- ✅ Can use differently-priced models

**Cons:**
- ❌ 3x cost (or more with premium models)
- ❌ Need to manage multiple API endpoints
- ❌ Models may have systematic biases

**Model Options:**

| Model | Endpoint | Use Case |
|-------|----------|----------|
| Claude Sonnet 4.5 | Azure Foundry | Primary judge |
| GPT-4o | Azure OpenAI | Second opinion |
| GPT-4o-mini | Azure OpenAI | Cost-effective third |
| Gemini 1.5 Pro | Google AI | Different perspective |

---

### 3. Self-Consistency (Same Model, Multiple Runs)

Run the same model multiple times with temperature > 0 for varied outputs.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SELF-CONSISTENCY (3-5 runs, temp=0.7)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Same Model, Same Input, Different Samples:                                 │
│                                                                              │
│  Run 1: Label 0, Conf 0.88                                                  │
│  Run 2: Label 0, Conf 0.82                                                  │
│  Run 3: Label 1, Conf 0.75                                                  │
│  Run 4: Label 0, Conf 0.90                                                  │
│  Run 5: Label 0, Conf 0.85                                                  │
│                                                                              │
│  ───────────────────────────────────────────                                │
│  FINAL: Label 0 (4/5 votes = 80% agreement)                                 │
│  Confidence: 0.80 (derived from agreement rate)                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Simple to implement
- ✅ Uses single model/endpoint
- ✅ Agreement rate = confidence

**Cons:**
- ❌ 3-5x cost per label
- ❌ May not help if model is systematically wrong

---

### 4. Cascade Voting (Escalation)

Start with cheap/fast strategy, escalate to expensive/accurate when uncertain.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CASCADE VOTING (Escalation)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ STEP 1: Strategy A (cheap, fast)                                   │    │
│  │                                                                     │    │
│  │ ──► Confidence ≥ 0.90?  ──► YES ──► Use this label ✓              │    │
│  │                         ──► NO  ──► Continue to Step 2             │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                               │                                             │
│                               ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ STEP 2: Strategy C (more context)                                  │    │
│  │                                                                     │    │
│  │ ──► Confidence ≥ 0.85?  ──► YES ──► Use this label ✓              │    │
│  │                         ──► NO  ──► Continue to Step 3             │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                               │                                             │
│                               ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ STEP 3: Full Voting (A + B + C)                                    │    │
│  │                                                                     │    │
│  │ ──► Weighted vote ──► Final label ✓                                │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Cost-efficient (only escalate when needed)
- ✅ Fast for clear cases
- ✅ Full accuracy for ambiguous cases

**Cons:**
- ❌ Complex implementation
- ❌ Requires confidence calibration

**Cost Estimate:**
- 70% resolved at Step 1: 0.7 × $0.001 = $0.0007
- 25% resolved at Step 2: 0.25 × $0.005 = $0.00125
- 5% need full voting: 0.05 × $0.008 = $0.0004
- **Average: $0.002** (vs $0.008 for always voting)

---

## Voting Algorithms

### Majority Voting

Simple: count votes, pick the majority.

```python
def majority_vote(labels: List[int]) -> int:
    """Simple majority voting."""
    return 1 if sum(labels) > len(labels) / 2 else 0
```

### Weighted Voting

Weight votes by strategy or model quality.

```python
def weighted_vote(
    labels: List[int],
    confidences: List[float],
    weights: List[float]
) -> tuple[int, float]:
    """Weighted voting with confidence."""
    weighted_sum = sum(
        (1 - label) * conf * weight  # 0 = reasoning, 1 = non-reasoning
        for label, conf, weight in zip(labels, confidences, weights)
    )
    total_weight = sum(
        conf * weight for conf, weight in zip(confidences, weights)
    )
    
    reasoning_score = weighted_sum / total_weight
    label = 0 if reasoning_score > 0.5 else 1
    confidence = abs(reasoning_score - 0.5) * 2  # Scale to 0-1
    
    return label, confidence
```

### Confidence-Weighted Voting

Use judge confidence as implicit weight.

```python
def confidence_vote(results: List[ClassificationResult]) -> tuple[int, float]:
    """Vote weighted by each judge's confidence."""
    reasoning_score = sum(
        r.confidence if r.label == 0 else 0 for r in results
    )
    non_reasoning_score = sum(
        r.confidence if r.label == 1 else 0 for r in results
    )
    
    total = reasoning_score + non_reasoning_score
    if reasoning_score > non_reasoning_score:
        return 0, reasoning_score / total
    else:
        return 1, non_reasoning_score / total
```

---

## Handling Disagreement

### Full Agreement (3/3)
```
Label: Use unanimous vote
Confidence: Average of individual confidences
Action: High reliability, no review needed
```

### Majority Agreement (2/3)
```
Label: Use majority vote
Confidence: Reduce by 10-20%
Action: Generally reliable, spot-check samples
```

### Full Disagreement (Tie or No Majority)
```
Label: Flag for manual review
Confidence: 0.5 (uncertain)
Action: 
  - Option 1: Use Strategy C (best single strategy)
  - Option 2: Manual label
  - Option 3: Exclude from training
```

---

## Implementation: Ensemble Judge

```python
class EnsembleJudge:
    def __init__(self, strategies: List[str] = ["A", "B", "C"]):
        self.judges = {
            "A": StrategyAJudge(),
            "B": StrategyBJudge(),
            "C": StrategyCJudge()
        }
        self.strategies = strategies
        self.weights = {"A": 0.2, "B": 0.3, "C": 0.5}
    
    def classify(self, record: dict) -> EnsembleResult:
        results = {}
        
        for strategy in self.strategies:
            if strategy == "A":
                results["A"] = self.judges["A"].classify(
                    record["userMessage"]
                )
            elif strategy == "B":
                results["B"] = self.judges["B"].classify_from_record(record)
            elif strategy == "C":
                results["C"] = self.judges["C"].classify_turn(
                    record["turnsArray"],
                    record["turnIndex"]
                )
        
        # Weighted vote
        final_label, final_confidence = weighted_vote(
            labels=[r.label for r in results.values()],
            confidences=[r.confidence for r in results.values()],
            weights=[self.weights[s] for s in results.keys()]
        )
        
        return EnsembleResult(
            label=final_label,
            confidence=final_confidence,
            individual_results=results,
            agreement=len(set(r.label for r in results.values())) == 1
        )
```

---

## Cost Comparison

| Method | Cost per Label | Reliability | Best For |
|--------|----------------|-------------|----------|
| Single Strategy A | $0.001 | Baseline | Bulk, deployment |
| Single Strategy C | $0.005 | Good | Production labeling |
| Strategy Voting (A+B+C) | $0.008 | Better | High-quality labels |
| Model Voting (3 models) | $0.015 | High | Gold standard |
| Cascade (adaptive) | ~$0.002 | Good | Cost-efficient |
| Self-Consistency (5 runs) | $0.025 | High | Uncertainty quantification |

---

## Recommendations

### For 120k Conversation Dataset

| Subset | Method | Estimated Cost |
|--------|--------|----------------|
| **Train (100k)** | Strategy C only | ~$500 |
| **Validation (10k)** | Strategy Voting (A+B+C) | ~$80 |
| **Test (10k)** | Model Voting (Claude + GPT) | ~$100 |
| **Total** | Mixed | **~$680** |

### Decision Flowchart

```
START
  │
  ├── Is this a gold-standard eval set?
  │     YES → Use Model Voting (3 models)
  │
  ├── Is this ambiguous (low Strategy A confidence)?
  │     YES → Use Strategy Voting (A+B+C)
  │
  ├── Is this multi-turn conversation?
  │     YES → Use Strategy C
  │
  └── Otherwise → Use Strategy A
```

---

## Appendix: Alternative Approaches

### 1. Human-in-the-Loop Voting
- LLM labels, human reviews disagreements
- Cost: $0.05-0.10 per human review
- Use for: Building trust in LLM labels

### 2. Active Learning Voting
- Train router on high-confidence labels first
- Use router uncertainty to prioritize labeling
- Iteratively improve with human feedback

### 3. Debate-Style Voting
- Two LLMs argue for different labels
- Third LLM adjudicates based on arguments
- Use for: Understanding edge cases

---

## Related

- [Strategy A](../strategies/strategy_a/STRATEGY_A.md)
- [Strategy B](../strategies/strategy_b/STRATEGY_B.md)
- [Strategy C](../strategies/strategy_c/STRATEGY_C.md)

