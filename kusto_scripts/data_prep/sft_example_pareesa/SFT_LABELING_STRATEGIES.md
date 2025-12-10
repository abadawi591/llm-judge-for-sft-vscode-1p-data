# SFT Labeling Strategies for Reasoning Classification

> **Goal:** Label ~120k curated Copilot Agent Mode conversations to train a routing model that classifies whether a request requires a reasoning-capable LLM.
>
> **Label:** `0` = Reasoning required | `1` = Non-reasoning sufficient

---

## TL;DR Decision Matrix

| Approach | Input to LLM Judge | Cost/Call | Accuracy | Recommended For |
|----------|-------------------|-----------|----------|-----------------|
| **A. Text Only** | User message | $0.001 | Baseline | First pass, deployment |
| **B. Text + Metrics** | User message + behavioral signals | $0.002 | Good | Historical data labeling |
| **C. Text + History** | User message + last N turns | $0.005 | Better | Multi-turn conversations |
| **D. Full Context** | All of the above | $0.01 | Best | Gold-standard eval set |

**Recommendation:** Use **Approach C** for most labeling, **Approach D** for 10% gold-standard set.

---

## Why Context Matters

Our telemetry analysis revealed that what the LLM *actually saw* is much richer than just the user message:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT THE LLM SAW (promptTokens = 10k-100k tokens)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [1] System Prompt (~3-5k tokens)                                           │
│      └── Instructions + 70+ tool definitions                                │
│                                                                              │
│  [2] Conversation History (grows per turn)                                  │
│      ├── Turn 1: User + Assistant                                           │
│      ├── Turn 2: User + Assistant                                           │
│      └── ...                                                                 │
│                                                                              │
│  [3] Current Turn                                                           │
│      └── User message (what we're classifying)                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Problem:** If we only show the LLM judge the user message, we're classifying based on ~1-5% of what the model actually saw.

**Example:**
- User message: *"now fix it"*
- Without context: Sounds simple → Label: 1 (non-reasoning)
- With context: 5th turn in complex debugging session → Label: 0 (reasoning)

---

## Approach A: Text Only (Baseline)

**Input:** Current user message only

```python
prompt = f"""Classify if this request requires a reasoning-capable LLM.

USER REQUEST:
{user_message}

Output ONLY: 0 (reasoning required) or 1 (non-reasoning sufficient)"""
```

| Pros | Cons |
|------|------|
| ✅ Cheapest (~$0.001/call) | ❌ Loses all context |
| ✅ Fastest | ❌ "Fix the bug" is ambiguous |
| ✅ Matches deployment input | ❌ Follow-ups misclassified |

**Use for:** Baseline comparison, deployment-time inference

---

## Approach B: Text + Behavioral Metrics

**Input:** User message + telemetry signals (what *actually happened*)

```python
prompt = f"""Classify if this request required a reasoning-capable LLM.

USER REQUEST:
{user_message}

OBSERVED BEHAVIOR:
- Prompt tokens: {prompt_tokens}
- Completion tokens: {completion_tokens}
- LLM calls: {llm_call_count}
- Tools used: {tool_list}
- Duration: {duration_ms}ms

Guidelines:
- High prompt tokens (>10k) → accumulated context, likely complex
- High completion tokens (>1500) + multiple LLM calls (>2) → likely reasoning (0)
- Low tokens (<500) + single call → likely non-reasoning (1)
- BUT: If behavior seems excessive for the request, consider 1

Output ONLY: 0 or 1"""
```

| Pros | Cons |
|------|------|
| ✅ Uses ground-truth signals | ❌ Still no conversational context |
| ✅ Detects over-complicated responses | ❌ Metrics alone can mislead |
| ✅ Objective, low variance | |

**Use for:** Post-hoc labeling of historical data

---

## Approach C: Text + Conversation History (RECOMMENDED)

**Input:** User message + last N turns of conversation

```python
def get_context_window(turns, current_idx):
    """Choose context based on conversation length."""
    if current_idx <= 3:
        return turns[:current_idx]  # All previous
    elif current_idx <= 10:
        return turns[max(0, current_idx-5):current_idx]  # Last 5
    else:
        return [turns[0]] + turns[current_idx-4:current_idx]  # Turn 1 + last 4

prompt = f"""Classify if the CURRENT request requires a reasoning-capable LLM.

CONVERSATION HISTORY:
{format_history(context_turns)}

CURRENT REQUEST (Turn {turn_index}):
{user_message}

Consider:
1. Does this build on previous context in complex ways?
2. Is there accumulated state (files modified, decisions made)?
3. Is this a simple follow-up or new complex direction?

Output ONLY: 0 or 1"""
```

| Pros | Cons |
|------|------|
| ✅ Captures context-dependent complexity | ❌ Higher cost (~5x baseline) |
| ✅ Handles follow-ups correctly | ❌ Long responses need truncation |
| ✅ Matches what model actually saw | |

**Use for:** Primary labeling approach for multi-turn conversations

---

## Approach D: Full Context (Gold Standard)

**Input:** Everything - history + metrics + available tools

> ⚠️ **Important Clarification:** This approach is for **labeling only**, not deployment.
> We use hindsight information (completion tokens, tool usage, duration) that is only 
> available *after* the LLM response. The router will never have access to this at 
> inference time. This is intentional: we're using the best available information to 
> generate high-quality labels, which we then distill into a simpler router model.

```python
prompt = f"""You are an expert classifier. Determine if this request required 
a reasoning-capable LLM based on ALL available information.

METADATA:
- Conversation length: {total_turns} turns
- Current turn: {turn_index}
- Available tools: {tool_count} tools

CONVERSATION HISTORY (last 5 turns):
{format_history(context_turns)}

CURRENT TURN:
User: {user_message}

Observed (hindsight signals - what actually happened):
- Prompt tokens: {prompt_tokens}
- Completion tokens: {completion_tokens}
- LLM calls: {llm_call_count}
- Tools used: {tools_used}
- Duration: {duration_ms}ms

CLASSIFY:
0 = Reasoning required (complex, multi-step, context-dependent)
1 = Non-reasoning sufficient (simple, direct, context-independent)

Output ONLY: 0 or 1"""
```

| Pros | Cons |
|------|------|
| ✅ Highest accuracy labels | ❌ Highest cost (~10x baseline) |
| ✅ Best for ambiguous cases | ❌ Uses hindsight (not available at inference) |
| ✅ Gold-standard quality | ❌ Requires careful train/test thinking |

**Use for:** Creating evaluation sets, labeling ambiguous samples. The labels are high quality because we use all available information, but the router will learn to predict these labels from limited input.

---

## Router Context Window Considerations

> **Key Constraint:** ModernBERT has an **8,192 token** context window, while the LLMs 
> it routes to (GPT-4, Claude, etc.) have 100k-200k+ tokens.

There are actually **two different mismatches** to consider:

### Mismatch 1: Labeling Time vs. Router Training (Knowledge Distillation ✅)

This IS knowledge distillation:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LABELING TIME (LLM Judge)              TRAINING TIME (Router SFT)         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Claude Sonnet/Opus sees:               Router learns from:                 │
│  ├── System prompt                      ├── User message                   │
│  ├── Last 5 turns of history           ├── (Optional) Turn index           │
│  ├── Current user message               └── Labels generated by LLM judge  │
│  ├── Behavioral metrics (hindsight)                                         │
│  └── Tool usage patterns                                                    │
│                                                                              │
│  OUTPUT: High-quality labels            OUTPUT: Trained router model        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**This IS knowledge distillation:** Teacher (LLM judge with full context) → Student (Router with limited input).

---

### Mismatch 2: Router Inference vs. LLM Inference (NOT Knowledge Distillation ⚠️)

This is the mismatch you're asking about — **routing under partial information** at inference time:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LIVE COPILOT SESSION (BOTH AT INFERENCE TIME)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [STEP 1] Router decides:               [STEP 2] LLM processes:             │
│  ├── Current user message               ├── System prompt (~3-5k tokens)   │
│  ├── (Maybe) Turn index                 ├── 70+ tool definitions            │
│  └── (Maybe) Last 1-2 turns             ├── FULL conversation history       │
│                                          ├── Current user message            │
│  Window: 8,192 tokens                   └── Retrieved files/context         │
│  Decision: reasoning model or not?                                           │
│                                          Window: 100,000+ tokens             │
│                                          Actually executes the task          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**This is NOT knowledge distillation.** The router makes a routing decision with **less 
information** than the LLM will eventually see. This is the real "triage nurse" problem:

- **Triage nurse (router):** Asks "What brings you in today?" → decides which doctor to assign
- **Doctor (LLM):** Gets full patient history, runs tests, makes full diagnosis

### Why Mismatch 2 Matters for Routing Quality

The router might make suboptimal decisions because it doesn't see:

| What Router Misses | Potential Impact |
|--------------------|------------------|
| Full conversation history | "fix it" looks simple, but it's turn 15 of complex debugging |
| System prompt complexity | Some sessions have more complex tool configurations |
| Retrieved file contents | User message is short, but retrieved files reveal complexity |
| Accumulated state | Previous turns modified 20 files, state is now tangled |

### Mitigations for Mismatch 2

1. **Turn index as a proxy signal**
   - Pass `[Turn 7/12]` to router → learns "later turns = likely more complex"
   - Cheap, available at inference, adds meaningful signal

2. **Summary metadata (future enhancement)**
   ```
   [Turn 7/12 | prev_files_modified: 12 | prev_tool_calls: 45]
   Fix the authentication bug
   ```
   These signals are cheap to compute and available at inference time.

3. **Accept bounded error**
   - Router can't be perfect with partial information
   - If 80% of complexity signal is in the user message, we're still winning
   - Goal is best tradeoff, not perfection

4. **Bias toward reasoning when uncertain**
   - If router is unsure, route to reasoning model (safer default)
   - Over-routing to reasoning costs money, under-routing costs quality

### The Fundamental Tradeoff

> **Can the router make a good decision with 8k tokens when the LLM sees 100k tokens?**

| Scenario | Router Accuracy | Why |
|----------|-----------------|-----|
| Turn 1 (no history yet) | ✅ High | User message contains all the signal |
| Explicit complexity ("implement OAuth2") | ✅ High | Keywords reveal complexity |
| Ambiguous follow-up ("do it", "now fix it") | ⚠️ Low | Needs history router doesn't have |
| Long history, short message | ⚠️ Medium | Turn index helps, but imperfect |

**Key insight:** The router doesn't need to see everything the LLM sees. It just needs 
enough signal to make a good routing decision. This is analogous to how a load balancer 
doesn't need to understand HTTP request bodies — it routes based on headers/metadata.

### Token Budget Analysis for Router

Given ModernBERT's 8,192 token window, here's what we can fit:

| Component | Approx Tokens | Notes |
|-----------|---------------|-------|
| System prompt / task instruction | ~100 | Fixed overhead |
| Current user message | ~50-500 | Varies by message |
| Turn index signal | ~10 | "[Turn 7/12]" |
| Last 1-2 turns of history | ~500-2000 | Compressed summaries |
| **Available budget** | **~5,500-7,500** | Comfortable headroom |

### SFT Format Implications

This affects which SFT format we should use for training the router:

| Format | Fits in 8k? | Recommended? |
|--------|-------------|--------------|
| **A: User message only** | ✅ Always | ✅ Default for deployment |
| **B: User message + turn index** | ✅ Always | ✅ Good tradeoff |
| **C: User message + last 5 turns** | ⚠️ Sometimes | ⚠️ Need truncation strategy |

### Recommendations for SFT Data Preparation

1. **Truncate history to fit 8k**: For Format C, ensure total tokens < 8,192
2. **Prefer Format A or B for deployment**: Simpler inputs, consistent performance
3. **Use Format C for evaluation only**: Test if history helps, but deploy with A/B
4. **Labels come from full context**: Even if router sees limited input, labels use Approach C/D

### What the Router Needs to Learn

The router must predict routing decisions from **limited signals**:

| Signal Available to Router | What It Can Infer |
|---------------------------|-------------------|
| User message text | Explicit complexity, keywords ("debug", "refactor") |
| Message length | Longer often = more complex |
| Turn index | Later turns often more context-dependent |
| Presence of code/file refs | Technical complexity |

The router does NOT need access to:
- Behavioral metrics (hindsight only)
- Full conversation history (just patterns)
- Actual LLM response (not available yet)

---

## Recommended Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LABELING PIPELINE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT: 120k curated conversations (100k train + 10k val + 10k test)        │
│                                                                              │
│  STEP 1: Label each TURN (not conversation)                                 │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • Each conversation has 3-20 turns                                         │
│  • Total turns to label: ~600k-800k                                         │
│  • Label at TURN level (each user message gets a label)                     │
│                                                                              │
│  STEP 2: Choose approach by turn position                                   │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • Turn 1 (first message): Approach A or B (no history yet)                 │
│  • Turns 2-5: Approach C with full history                                  │
│  • Turns 6+: Approach C with last 5 turns                                   │
│  • 10% sample: Approach D (gold standard)                                   │
│                                                                              │
│  STEP 3: Validate                                                           │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • Human review 5% sample                                                    │
│  • Check label distribution (expect ~60-70% reasoning for agent mode)       │
│  • Compare Approach A vs C labels for systematic differences                │
│                                                                              │
│  STEP 4: Create SFT datasets                                                │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • Format A: (user_message) → label                    [for deployment]     │
│  • Format B: (user_message, turn_index) → label        [context-aware]      │
│  • Format C: (history + user_message) → label          [max accuracy]       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SFT Output Formats

### Format A: Minimal (Deployment-Ready)

```json
{
  "messages": [
    {"role": "system", "content": "Classify if the request requires a reasoning-capable LLM. Output 0 (reasoning) or 1 (non-reasoning)."},
    {"role": "user", "content": "Fix the authentication bug in the login flow"},
    {"role": "assistant", "content": "0"}
  ]
}
```

### Format B: With Turn Index

```json
{
  "messages": [
    {"role": "system", "content": "Classify if the request requires a reasoning-capable LLM. Consider the turn number. Output 0 or 1."},
    {"role": "user", "content": "[Turn 7/12] Fix the authentication bug in the login flow"},
    {"role": "assistant", "content": "0"}
  ]
}
```

### Format C: With History (Evaluation Only)

```json
{
  "messages": [
    {"role": "system", "content": "Classify the CURRENT request considering conversation history. Output 0 or 1."},
    {"role": "user", "content": "History:\n[Turn 1] User: Help me build a login system\n[Turn 2] User: Add password hashing\n...\n\nCurrent [Turn 7]: Fix the authentication bug"},
    {"role": "assistant", "content": "0"}
  ]
}
```

---

## Key Decisions Needed from Team

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **Label granularity** | Per-conversation vs per-turn | **Per-turn** (more training data, finer control) |
| **Primary labeling approach** | A, B, C, or D | **C** (best accuracy/cost tradeoff for generating labels) |
| **Context window for labeling** | Fixed N vs adaptive | **Adaptive** (based on convo length) |
| **Gold standard %** | 5%, 10%, 20% | **10%** (enough for eval, not too expensive) |
| **Human review %** | 1%, 5%, 10% | **5%** (catch systematic errors) |
| **SFT format for router training** | A, B, or C | **A or B** (must fit in ModernBERT's 8k window) |
| **Router input at deployment** | Message only vs message + index | **B** (message + turn index adds signal, minimal cost) |

### Labeling vs. Training Distinction

> ⚠️ **Critical:** The approach for **labeling** (how LLM judge generates labels) is different 
> from the approach for **SFT training** (what the router learns from).
>
> - **Labeling:** Use Approach C or D (rich context → high-quality labels)
> - **SFT Training:** Use Format A or B (limited input → matches deployment)
>
> This is knowledge distillation: rich teacher → compact student.

---

## Cost Estimates

Assuming GPT-4o-mini for labeling (~$0.15/1M input tokens, ~$0.60/1M output tokens):

| Scenario | Turns | Approach | Est. Cost |
|----------|-------|----------|-----------|
| 120k convos × 5 avg turns | 600k | A (text only) | ~$100 |
| 120k convos × 5 avg turns | 600k | C (with history) | ~$500 |
| 60k turns (10% gold) | 60k | D (full context) | ~$100 |
| **Total (recommended mix)** | | C + D | **~$600-800** |

---

## Next Steps

1. [ ] **Team decision:** Confirm approach (recommend C + 10% D)
2. [ ] **Run pilot:** Label 1k turns with each approach, compare
3. [ ] **Human baseline:** Have 2-3 humans label 500 turns for agreement check
4. [ ] **Full labeling:** Run on 120k conversations (~600k turns)
5. [ ] **Validation:** Compare approach A vs C systematic differences
6. [ ] **SFT training:** Train classifier on labeled data

---

## Appendix: Available Fields in Curated Data

From our data curation pipeline, each turn includes:

```json
{
  "conversationId": "abc-123",
  "turnIndex": 5,
  "userMessage": "Fix the authentication bug",
  "modelMessage": "I've identified the issue...",
  "llmCalls": [
    {"promptTokens": 45000, "completionTokens": 1200, "model": "gpt-4o"}
  ],
  "turnSummary": {
    "maxPromptTokens": 45000,
    "llmCallCount": 3,
    "hasTrajectory": true
  },
  "toolCounts": {"read_file": 2, "write_file": 1},
  "availableTools": ["read_file", "write_file", "grep_search", ...],
  "availableToolCount": 77
}
```

### Field Usage by Approach

| Field | Approach A | Approach B | Approach C | Approach D | Router (SFT) |
|-------|:----------:|:----------:|:----------:|:----------:|:------------:|
| `userMessage` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `turnIndex` | ❌ | ❌ | ✅ | ✅ | ✅ (Format B) |
| `modelMessage` (history) | ❌ | ❌ | ✅ | ✅ | ⚠️ Truncated |
| `promptTokens` | ❌ | ✅ | ❌ | ✅ | ❌ (hindsight) |
| `completionTokens` | ❌ | ✅ | ❌ | ✅ | ❌ (hindsight) |
| `llmCallCount` | ❌ | ✅ | ❌ | ✅ | ❌ (hindsight) |
| `toolCounts` | ❌ | ✅ | ❌ | ✅ | ❌ (hindsight) |
| `availableToolCount` | ❌ | ❌ | ❌ | ✅ | ❌ (static) |

> **Note on `promptTokens`:** This is a valuable signal for labeling (high prompt tokens = accumulated 
> context = likely complex). It's used in Approaches B and D but NOT available to the router at 
> deployment time since it's computed after the LLM processes the request.

