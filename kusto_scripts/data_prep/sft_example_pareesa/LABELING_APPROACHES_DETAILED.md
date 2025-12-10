# Detailed Labeling Approaches for Reasoning Classification

## Executive Summary

This document proposes specific labeling strategies for classifying whether a user request requires a reasoning-capable LLM. Based on our analysis of multi-turn conversation telemetry, we recommend **context-aware labeling** that includes previous turns and behavioral signals.

---

## Key Insight: Context Matters

From our telemetry investigation, we confirmed:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     WHAT THE LLM ACTUALLY SAW                            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ SYSTEM PROMPT (constant ~3-5k tokens)                           │    │
│  │ - Instructions, persona, capabilities                           │    │
│  │ - Tool definitions (adds significant tokens!)                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              +                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ CONVERSATION HISTORY (grows with each turn)                     │    │
│  │ - Turn 1: User message + Assistant response                     │    │
│  │ - Turn 2: User message + Assistant response                     │    │
│  │ - ...                                                           │    │
│  │ - Turn N-1: User message + Assistant response                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              +                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ CURRENT TURN (what we're classifying)                           │    │
│  │ - User message (Turn N)                                         │    │
│  │ - [Within turn: tool results accumulate across LLM calls]       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  TOTAL = promptTokens (can be 10k-100k+ tokens)                         │
└──────────────────────────────────────────────────────────────────────────┘
```

**Implication:** If we only show the LLM judge the current user message, we're asking it to classify based on 1% of what the original model saw!

---

## Proposed Labeling Approaches

### Approach 1: Current Turn Only (Baseline)

**What LLM Judge Sees:**
- Current user message only

**When to Use:**
- Quick baseline
- When context isn't available
- For first-turn classification

**Prompt Template:**
```
You are classifying whether a user request requires a reasoning-capable LLM.

USER REQUEST:
{current_user_message}

Based ONLY on this request, determine:
- 0 = Reasoning model required (complex, multi-step, ambiguous)
- 1 = Non-reasoning model sufficient (simple, direct, factual)

Output ONLY: 0 or 1
```

**Limitations:**
- ❌ "Fix the bug" could be trivial or complex depending on context
- ❌ Follow-up questions lose all context
- ❌ Accumulated complexity is invisible

---

### Approach 2: Current Turn + Behavioral Signals

**What LLM Judge Sees:**
- Current user message
- Token metrics (prompt, completion)
- Tool usage summary
- LLM call count within turn
- Turn duration

**When to Use:**
- When you have telemetry data
- For post-hoc labeling of historical data
- When you want ground-truth behavioral signals

**Prompt Template:**
```
You are classifying whether a user request required a reasoning-capable LLM.

USER REQUEST:
{current_user_message}

OBSERVED BEHAVIOR (what actually happened):
- Prompt tokens used: {prompt_tokens}
- Completion tokens generated: {completion_tokens}
- Number of LLM calls: {llm_call_count}
- Tools invoked: {tool_list}
- Tool invocation count: {total_tool_calls}
- Turn duration: {turn_duration_ms}ms

CLASSIFICATION GUIDELINES:
Consider both the request complexity AND the observed behavior.

Indicators of REASONING REQUIRED (0):
- High token usage (>2000 completion tokens)
- Multiple LLM calls (>2 calls)
- Complex tool chains (file reads → edits → terminal)
- Long duration (>30 seconds)

Indicators of NON-REASONING SUFFICIENT (1):
- Low token usage (<500 completion tokens)
- Single LLM call
- Simple or no tool usage
- Quick response (<10 seconds)

However, also consider if the behavior was EXCESSIVE for the request:
- If a simple request triggered complex behavior, it may indicate
  the model over-complicated things, not that reasoning was needed.

Output ONLY: 0 or 1
```

**Advantages:**
- ✅ Uses ground truth signals
- ✅ Can detect over-complicated responses
- ✅ Objective metrics reduce labeling variance

---

### Approach 3: Previous N Turns + Current Turn (RECOMMENDED)

**What LLM Judge Sees:**
- Last N turns of conversation (user + assistant messages)
- Current user message
- Conversation metadata (total turns, current turn index)

**When to Use:**
- For multi-turn conversations (agent mode)
- When context significantly affects complexity
- For production routing that will have access to history

**How to Choose N:**
| Conversation Length | Recommended N |
|---------------------|---------------|
| 1-3 turns | All previous turns |
| 4-10 turns | Last 3-5 turns |
| 11+ turns | Last 5 turns + turn 1 (initial context) |

**Prompt Template:**
```
You are classifying whether the CURRENT user request requires a reasoning-capable LLM.

CONVERSATION CONTEXT:
- Total turns in conversation: {total_turns}
- Current turn: {current_turn_index}
- Conversation topic/pattern so far: (inferred from history below)

CONVERSATION HISTORY (last {N} turns):
---
[Turn {turn_n-2}]
User: {user_message_n-2}
Assistant: {assistant_response_n-2_summary}

[Turn {turn_n-1}]
User: {user_message_n-1}
Assistant: {assistant_response_n-1_summary}
---

CURRENT REQUEST (Turn {current_turn_index}):
User: {current_user_message}

CLASSIFICATION TASK:
Considering the conversation history and accumulated context, does THIS specific
request require a reasoning-capable model?

Key considerations:
1. Does this request BUILD on previous context in complex ways?
2. Would a model WITHOUT this history misunderstand the request?
3. Is there accumulated state (files modified, decisions made) that matters?
4. Is this a simple follow-up or a new complex direction?

Output ONLY: 0 (reasoning required) or 1 (non-reasoning sufficient)
```

**Advantages:**
- ✅ Captures context-dependent complexity
- ✅ Matches what the original model actually saw
- ✅ Handles follow-up questions correctly

**Implementation Note:**
For assistant responses, you may want to summarize long responses to save tokens:
```python
def summarize_response(response, max_chars=500):
    if len(response) <= max_chars:
        return response
    return response[:max_chars] + "... [truncated]"
```

---

### Approach 4: Full Context + Behavioral Signals (Maximum Information)

**What LLM Judge Sees:**
- Previous N turns (user + assistant messages)
- Current user message
- Token metrics for current turn
- Tool usage for current turn
- Available tools list
- Conversation metadata

**When to Use:**
- For highest accuracy labeling
- When labeling cost is not a concern
- For creating gold-standard evaluation sets

**Prompt Template:**
```
You are an expert classifier determining whether a user request required a 
reasoning-capable LLM.

═══════════════════════════════════════════════════════════════════════════
CONVERSATION METADATA
═══════════════════════════════════════════════════════════════════════════
- Conversation ID: {conversation_id}
- Total turns: {total_turns}
- Current turn: {current_turn_index}
- Conversation bucket: {bucket} (short/medium/long)

═══════════════════════════════════════════════════════════════════════════
AVAILABLE TOOLS (what the model could use)
═══════════════════════════════════════════════════════════════════════════
{available_tools_list}
Total available: {available_tool_count} tools

═══════════════════════════════════════════════════════════════════════════
CONVERSATION HISTORY (last {N} turns)
═══════════════════════════════════════════════════════════════════════════
{formatted_conversation_history}

═══════════════════════════════════════════════════════════════════════════
CURRENT TURN TO CLASSIFY
═══════════════════════════════════════════════════════════════════════════
User Request: {current_user_message}

Observed Processing:
- Prompt tokens: {prompt_tokens}
- Completion tokens: {completion_tokens}
- LLM calls made: {llm_call_count}
- Tools used: {tools_used}
- Processing time: {turn_duration_ms}ms

═══════════════════════════════════════════════════════════════════════════
CLASSIFICATION
═══════════════════════════════════════════════════════════════════════════
Based on ALL available information, classify this request:

0 = REASONING REQUIRED
    - Complex multi-step problem solving
    - Requires understanding accumulated context
    - Ambiguous request needing interpretation
    - Debugging, refactoring, or architectural decisions
    - High observed complexity justified by request

1 = NON-REASONING SUFFICIENT  
    - Simple, direct request
    - Context-independent question
    - Straightforward lookup or simple edit
    - Observed complexity seems excessive for request

Output your classification as a single digit: 0 or 1
```

---

## Comparison Matrix

| Approach | Context | Behavior | Token Cost | Accuracy | Best For |
|----------|---------|----------|------------|----------|----------|
| 1. Current Only | ❌ | ❌ | Low | Baseline | Quick labeling |
| 2. + Behavioral | ❌ | ✅ | Medium | Good | Historical data |
| 3. + N Turns | ✅ | ❌ | Medium | Better | Multi-turn convos |
| 4. Full Context | ✅ | ✅ | High | Best | Gold standard |

---

## Recommended Labeling Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED LABELING PIPELINE                         │
└─────────────────────────────────────────────────────────────────────────┘

Step 1: STRATIFY your data
        ├── Short conversations (3-5 turns)  → Use Approach 3 (all context)
        ├── Medium conversations (6-10 turns) → Use Approach 3 (last 5 turns)
        └── Long conversations (11-20 turns)  → Use Approach 4 (last 5 + metrics)

Step 2: BATCH labeling calls
        ├── Group similar-length conversations
        ├── Use consistent prompts per batch
        └── Include 10% overlap for consistency checks

Step 3: VALIDATE labels
        ├── Sample 5% for human review
        ├── Check label distribution (expect ~60-70% reasoning for agent mode)
        └── Look for systematic errors (e.g., all short requests = non-reasoning)

Step 4: CREATE multiple training formats
        ├── Format A: Text-only (for deployment)
        ├── Format B: Text + turn count (for context-aware deployment)
        └── Format C: Full context (for evaluation only)
```

---

## Specific Signal Weights

Based on our telemetry analysis, here are suggested weightings for behavioral signals:

| Signal | Strong Indicator of Reasoning (0) | Strong Indicator of Non-Reasoning (1) |
|--------|-----------------------------------|---------------------------------------|
| **LLM Call Count** | > 3 calls | 1 call |
| **Completion Tokens** | > 1500 tokens | < 300 tokens |
| **Tool Count** | > 4 unique tools | 0-1 tools |
| **Tool Chain Pattern** | read → edit → run → edit | Single read or single edit |
| **Turn Duration** | > 60 seconds | < 10 seconds |
| **Conversation Length** | Later turns (5+) | First 2 turns |
| **Request Length** | > 200 words | < 20 words |

**Note:** These are guidelines, not rules. The LLM judge should use judgment, not thresholds.

---

## Edge Cases to Consider

### 1. Simple Request, Complex Execution
```
Request: "fix the bug"
Behavior: 5 LLM calls, 8 tool invocations, 45 seconds

Classification: Consider 0 (reasoning)
Rationale: Even if request was simple, if context required complex work,
           a reasoning model was likely needed.
```

### 2. Complex Request, Simple Execution
```
Request: "Refactor this entire module to use dependency injection,
          ensure all tests pass, and update the documentation"
Behavior: 1 LLM call, 200 tokens, 3 seconds

Classification: Consider 1 (non-reasoning)
Rationale: Despite complex request, the model handled it simply.
           Perhaps it declined, or the file was already well-structured.
           Check the actual response!
```

### 3. Context-Dependent Ambiguity
```
Turn 1: "Let's build a todo app"
Turn 2: "Add authentication"
Turn 3: "Now add the database"  ← Classifying this

Without context: Sounds like simple addition
With context: This is the 3rd step in an evolving architecture
Classification: 0 (reasoning) - accumulated decisions matter
```

---

## Final Recommendations

1. **Always include at least 2-3 previous turns** for agent-mode conversations
2. **Use behavioral signals** when available - they're ground truth
3. **Create separate evaluation sets** using full context to understand model limits
4. **Train on minimal input** (text-only or text + turn count) for deployment efficiency
5. **Validate with humans** on 5% sample to catch systematic LLM judge errors

---

## Appendix: Sample Code for Formatting Labeling Prompts

```python
def format_labeling_prompt(conversation: dict, approach: str = "full") -> str:
    """Format a conversation for LLM judge labeling."""
    
    turns = conversation["turnsArray"]
    current_turn_idx = len(turns) - 1
    current_turn = turns[current_turn_idx]
    
    if approach == "current_only":
        return f"""USER REQUEST:
{current_turn["userMessage"]}

Classify: 0 (reasoning required) or 1 (non-reasoning sufficient)
Output ONLY: 0 or 1"""
    
    elif approach == "with_history":
        # Get last N turns
        N = min(5, current_turn_idx)
        history = turns[max(0, current_turn_idx - N):current_turn_idx]
        
        history_text = ""
        for i, turn in enumerate(history):
            turn_num = current_turn_idx - N + i + 1
            history_text += f"""
[Turn {turn_num}]
User: {turn["userMessage"]}
Assistant: {turn["modelMessage"][:500]}{"..." if len(turn["modelMessage"]) > 500 else ""}
"""
        
        return f"""CONVERSATION HISTORY:
{history_text}

CURRENT REQUEST (Turn {current_turn_idx + 1}):
{current_turn["userMessage"]}

Classify this request considering the full context.
Output ONLY: 0 or 1"""
    
    elif approach == "full":
        # Include history + behavioral signals
        summary = current_turn.get("turnSummary", {})
        tools = current_turn.get("toolCounts", {})
        
        # ... (full implementation as shown in Approach 4)
```

