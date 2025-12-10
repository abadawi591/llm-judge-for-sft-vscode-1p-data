# LLM Judge Strategies for Reasoning Classification

## Context

You've curated rich conversation data with significantly more fields than the original pipeline. This document explores different LLM judge strategies and SFT formats to leverage this additional context.

## Available Fields in Your Curated Data

| Category | Fields |
|----------|--------|
| **Conversation** | `conversationId`, `userName`, `capturedTurnCount`, `bucket` |
| **Turn Content** | `userMessage`, `modelMessage`, `turnIndex` |
| **Token Metrics** | `maxPromptTokens`, `totalCompletionTokens`, `llmCallCount` |
| **Tool Usage** | `toolCounts`, `availableTools`, `availableToolCount` |
| **Performance** | `turnDurationMs`, `numRequests` |
| **LLM Calls** | Per-call `model`, `promptTokens`, `completionTokens` |

---

## The Core Question: More Fields or Fewer?

### Arguments for Minimal Fields (Current Approach)

| Pros | Cons |
|------|------|
| ✅ Simpler for LLM to process | ❌ May miss important context |
| ✅ Faster inference | ❌ Can't leverage behavioral signals |
| ✅ Lower token cost | ❌ Classification may be superficial |
| ✅ Easier to interpret | ❌ Ignores multi-turn dynamics |

**When to use:** When you want the classifier to make decisions the same way a human would at first glance—based purely on the text of the request.

### Arguments for Rich Context

| Pros | Cons |
|------|------|
| ✅ Better accuracy potential | ❌ More complex prompts |
| ✅ Can learn from behavioral signals | ❌ Higher token cost |
| ✅ Captures multi-turn patterns | ❌ Risk of overfitting to spurious correlations |
| ✅ Uses ground truth performance data | ❌ Harder to interpret decisions |

**When to use:** When you have strong signals (like actual model behavior) that correlate with the classification target.

### Industry Standard Practice

**Best practice from SFT literature:**
1. **Start simple**, add complexity only if needed
2. **Use behavioral signals** when available (token usage, latency, tool calls)
3. **Multi-turn context** helps for conversation-aware classification
4. **Separate concerns**: Use different models for different aspects if needed

---

## Three Proposed SFT Strategies

---

## Strategy 1: Text-Only Classification (Baseline)

### Approach
Same as Pareesa's approach—only show the user message to the LLM judge.

### SFT Format

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Classify whether this user request requires a reasoning-capable LLM.\nOutput 0 if reasoning is required.\nOutput 1 if a fast, non-reasoning model is sufficient.\nRespond with only: 0 or 1"
    },
    {
      "role": "user",
      "content": "can you help me debug this recursive function that's causing a stack overflow?"
    },
    {
      "role": "assistant",
      "content": "0"
    }
  ]
}
```

### Rationale
- **Simplicity**: Easy to implement and understand
- **Generalization**: Doesn't overfit to specific behavioral patterns
- **Deployment**: Can classify new requests before any processing happens

### Best For
- Real-time routing decisions
- When you want human-interpretable classifications
- When behavioral data isn't available at inference time

### Labeling Strategy
Use LLM judge (e.g., GPT-4) to classify based on:
- Complexity of the request
- Whether it requires multi-step reasoning
- Presence of ambiguity or edge cases

---

## Strategy 2: Behavioral Signal Classification

### Approach
Include observed behavioral signals that correlate with reasoning requirements—but NOT the actual content that might leak the answer.

### SFT Format

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Based on the user request and observed processing metrics, classify whether this request required a reasoning-capable LLM.\n\nMetrics provided:\n- Token usage (indicates complexity)\n- Tool calls (indicates agentic behavior)\n- LLM call count (indicates iterative reasoning)\n- Turn duration (indicates processing time)\n\nOutput 0 if reasoning was required.\nOutput 1 if a fast model would have sufficed.\nRespond with only: 0 or 1"
    },
    {
      "role": "user",
      "content": "REQUEST: can you help me debug this recursive function that's causing a stack overflow?\n\nMETRICS:\n- Prompt tokens: 2,847\n- Completion tokens: 1,523\n- LLM calls: 4\n- Tools used: [\"read_file\", \"grep\", \"edit_file\"]\n- Turn duration: 45,230ms"
    },
    {
      "role": "assistant",
      "content": "0"
    }
  ]
}
```

### Rationale
- **Ground Truth Signals**: Token usage and tool calls are strong indicators of actual complexity
- **Objective Metrics**: Less subjective than text-only classification
- **Learned Patterns**: Model can learn "high token + many tools = reasoning needed"

### Best For
- Post-hoc analysis and quality assessment
- When you have historical data with metrics
- Building a classifier that learns from actual model behavior

### Labeling Strategy
**Heuristic-based** (no LLM judge needed):
- `reasoning_required = (llmCallCount > 2) OR (toolCount > 3) OR (completionTokens > 1000)`
- Or use clustering on metrics to find natural groupings

---

## Strategy 3: Multi-Turn Conversation Context

### Approach
Include previous turns to capture conversation dynamics. Some requests only become "reasoning-required" in context.

### SFT Format

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Given a multi-turn conversation, classify whether the LATEST user request requires a reasoning-capable LLM.\n\nConsider:\n- Does the request build on previous context?\n- Is there accumulated state or complexity?\n- Would a simpler model lose track of the conversation?\n\nOutput 0 if reasoning is required for the latest turn.\nOutput 1 if a fast model would suffice.\nRespond with only: 0 or 1"
    },
    {
      "role": "user",
      "content": "CONVERSATION HISTORY:\n\n[Turn 1]\nUser: I'm building a React app with authentication\nAssistant: I'll help you set up authentication. Let me check your current setup...\n\n[Turn 2]\nUser: Now add role-based access control\nAssistant: I'll implement RBAC. First, let me understand your user model...\n\n[Turn 3 - CLASSIFY THIS]\nUser: The admin role should also inherit from manager, but with extra permissions\n\nCLASSIFY TURN 3:"
    },
    {
      "role": "assistant",
      "content": "0"
    }
  ]
}
```

### Rationale
- **Context Matters**: "fix the bug" means different things at turn 1 vs turn 10
- **Accumulated Complexity**: Later turns often build on earlier decisions
- **Realistic Routing**: Production systems need to consider conversation state

### Best For
- Agent-mode conversations with many turns
- When earlier context influences complexity
- Building conversation-aware routing systems

### Labeling Strategy
Use LLM judge with full conversation context, or use behavioral metrics from the specific turn.

---

## Comparison Summary

| Strategy | Input Fields | Labeling | Best Signal | Use Case |
|----------|--------------|----------|-------------|----------|
| **1. Text-Only** | userMessage | LLM Judge | Request complexity | Real-time routing |
| **2. Behavioral** | userMessage + metrics | Heuristics | Actual model behavior | Post-hoc analysis |
| **3. Multi-Turn** | Full conversation | LLM Judge | Contextual complexity | Agent-mode routing |

---

## Recommendation

### For Your Project

Given that you have rich multi-turn data with token metrics and tool usage, I recommend a **hybrid approach**:

1. **Primary Classifier (Strategy 1)**: Train on text-only for real-time routing
2. **Validation Set (Strategy 2)**: Use behavioral metrics to validate labels
3. **Multi-Turn Subset (Strategy 3)**: For conversations with 5+ turns, include context

### Practical Implementation

```
Phase 1: Create labels using Strategy 2 (behavioral heuristics)
         - Fast, no LLM cost, uses ground truth metrics
         
Phase 2: Train classifier using Strategy 1 format (text-only)
         - Deployable for real-time routing
         
Phase 3: Evaluate on Strategy 3 subset (multi-turn)
         - Understand where text-only fails
```

### Key Insight

**The best approach separates labeling strategy from training format:**
- **Label** using rich signals (behavioral metrics, multi-turn context)
- **Train** on minimal input (text-only) for deployment efficiency
- **Evaluate** on both to understand model limitations

---

## References

- OpenAI Fine-tuning Guide: https://platform.openai.com/docs/guides/fine-tuning
- Anthropic Constitutional AI: Using AI feedback for training data
- LLM-as-Judge: https://arxiv.org/abs/2306.05685
- Self-Instruct: Using model outputs to generate training data

