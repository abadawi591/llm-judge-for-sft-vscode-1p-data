# Understanding the Token Data Schema

This document explains how tokens are tracked in GitHub Copilot (VS Code) agent mode telemetry.

**Related Queries:**
- `exploration/token_mechanics/49_single_turn_with_truncation.kql` - Full token breakdown with truncation detection
- `exploration/token_mechanics/50_verify_system_across_turns.kql` - Verify system tokens across turns
- `exploration/token_mechanics/51_verify_system_across_conversations.kql` - Verify system tokens across conversations

---

## 1. Token Tracking Levels

### Q: On what level are trajectories tracked? Per LLM call, message, or cumulative?

**Per LLM call** - Each trajectory is a **snapshot** of what's sent to the API for that specific call.

```
TURN 1 (messageId: abc123)
│
├── LLM Call 1: trajectory = [system, user]
│                            → Model decides to call read_file
│
├── LLM Call 2: trajectory = [system, user, assistant, tool_result_1]
│                            → Model decides to call grep
│
├── LLM Call 3: trajectory = [system, user, assistant, tool_result_1, assistant, tool_result_2]
│                            → Model gives final answer
│
└── END OF TURN
```

Each call's trajectory **includes everything from previous calls** within that turn - it's **cumulative within the turn**. That's why `toolResultTokens` keeps growing.

### Q: Why is `userTokens` constant across all LLM calls in a turn?

All LLM calls within a turn share the **same messageId**. The user sent ONE message that triggered the entire turn:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  USER SENDS ONE MESSAGE                                                     │
│  ════════════════════════════════════════════════════════════════════════   │
│                                                                             │
│  "Please read my config file and run the tests"                            │
│                                                                             │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  TURN BEGINS (messageId: abc-123)                                   │   │
│  │                                                                      │   │
│  │  LLM Call 1: "I'll read the config file..."                         │   │
│  │       → calls read_file tool                                         │   │
│  │                                                                      │   │
│  │  LLM Call 2: "I see the config. Now running tests..."               │   │
│  │       → calls run_terminal tool                                      │   │
│  │                                                                      │   │
│  │  LLM Call 3: "Tests complete! Here are the results..."              │   │
│  │       → final response (no tool)                                     │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  All 3 LLM calls share the SAME user message = SAME userTokens             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. What is "Trajectory"?

**Trajectory** = The full list of messages being sent to the LLM at that moment.

Think of it as a **snapshot** of the conversation context for each API call:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TRAJECTORY for LLM Call 3                                                  │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  [                                                                          │
│    {"role": "system",    "content": "[system prompt + tool defs]"},  14K   │
│    {"role": "user",      "content": "Please read my config..."},      4K   │
│    {"role": "assistant", "content": "I'll read the file..."},        150   │
│    {"role": "tool",      "content": "[config file contents]"},      5000   │
│    {"role": "assistant", "content": "Running tests..."},             100   │
│    {"role": "tool",      "content": "[terminal output]"},           8000   │
│  ]                                                                          │
│                                                                             │
│  trajectoryTotal = 14,000 + 4,000 + 150 + 5,000 + 100 + 8,000 = 31,250     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What does `hasTrajectory = true/false` mean?

| Value | Meaning |
|-------|---------|
| `hasTrajectory = true` | The INPUT telemetry event was captured and has `messagesJson` populated. We can see the role breakdown. |
| `hasTrajectory = false` | The INPUT event is missing or `messagesJson` is empty. Telemetry gap - we only have `promptTokens`. |

---

## 3. Why `promptTokens` Seems Inflated at First Glance

### The Question
> "Why is `promptTokens` already 25,000 for the very first message in a conversation?"

### The Answer: Tool Definitions Are Always Included

Even before ANY tool is invoked, the first LLM call already has ~15-25K tokens because **tool definitions are part of the system message**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  FIRST LLM CALL - BEFORE ANY TOOLS ARE USED                                 │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  SYSTEM PROMPT                                            ~3,000 tokens│ │
│  │  ─────────────────────────────────────────────────────────────────────│ │
│  │  "You are a helpful coding assistant..."                              │ │
│  │  "Be concise, follow best practices..."                               │ │
│  │  "You have access to tools..."                                        │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  TOOL DEFINITIONS (JSON Schemas)              ~8,000-12,000 tokens    │ │
│  │  ─────────────────────────────────────────────────────────────────────│ │
│  │                                                                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │
│  │  │  read_file   │ │  write_file  │ │ grep_search  │ │ run_terminal │ │ │
│  │  │  ~400 tokens │ │  ~400 tokens │ │  ~350 tokens │ │  ~500 tokens │ │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ │ │
│  │                                                                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │
│  │  │  list_dir    │ │  web_search  │ │  edit_file   │ │ ... 15 more  │ │ │
│  │  │  ~300 tokens │ │  ~450 tokens │ │  ~500 tokens │ │  ~5000 total │ │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ │ │
│  │                                                                        │ │
│  │  ← THE "OVERHEAD" - You pay for tool AVAILABILITY even if unused! →   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  USER MESSAGE                                          ~100-5,000 tokens│ │
│  │  ─────────────────────────────────────────────────────────────────────│ │
│  │  "How do I fix this bug in my code?"                                  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════   │
│  TOTAL BASELINE: ~12,000-20,000 tokens BEFORE any tool is invoked!         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Tool Availability ≠ Tool Invocation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  TOOL DEFINITIONS (always sent)     vs     TOOL RESULTS (only when used)   │
│  ═════════════════════════════════        ═══════════════════════════════  │
│                                                                             │
│  Cost: ~8-12K tokens                      Cost: Variable (0-200K+)         │
│  When: EVERY LLM call                     When: After tool is invoked       │
│                                                                             │
│  ┌─────────────────────────────┐          ┌─────────────────────────────┐  │
│  │ {                           │          │ {                           │  │
│  │   "name": "read_file",      │          │   "role": "tool",           │  │
│  │   "description": "...",     │          │   "content": "// Contents   │  │
│  │   "parameters": {           │          │     of the file that was    │  │
│  │     "type": "object",       │          │     read... could be 50K+   │  │
│  │     "properties": {...}     │          │     tokens for large files" │  │
│  │   }                         │          │ }                           │  │
│  │ }                           │          │                             │  │
│  └─────────────────────────────┘          └─────────────────────────────┘  │
│                                                                             │
│  LLM needs this to know tools exist       LLM needs this to see results    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Fixed vs Growing Fields Within a Turn

### System and User Tokens are CONSTANT within a Turn

Within a single turn (same `messageId`), these fields remain **constant across all LLM calls**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  TOKEN BEHAVIOR WITHIN A TURN (9 LLM calls)                                 │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  callIndex │ systemTokens │ userTokens │ assistantTokens │ toolResultTokens │
│  ══════════╪══════════════╪════════════╪═════════════════╪══════════════════│
│      1     │    14,722    │   3,916    │        0        │        0         │
│      2     │    14,722    │   3,916    │      144        │     1,312        │
│      3     │    14,722    │   3,916    │      144        │    13,006        │
│      4     │    14,722    │   3,916    │      343        │    36,505        │
│      5     │    14,722    │   3,916    │      343        │    57,846        │
│      6     │    14,722    │   3,916    │      343        │    91,772        │
│      7     │    14,722    │   3,916    │      343        │   122,788        │
│      8     │    14,722    │   3,916    │      447        │   148,197        │
│      9     │    14,722    │   3,916    │      533        │   182,376        │
│            │              │            │                 │                  │
│            │   CONSTANT   │  CONSTANT  │     GROWS       │     GROWS        │
│            │      ↓       │     ↓      │       ↓         │       ↓          │
│            │  Same system │ Same user  │  Model's prior  │ Tool outputs     │
│            │  prompt +    │ question   │  responses      │ accumulate       │
│            │  tool defs   │ triggered  │  accumulate     │                  │
│            │              │ this turn  │                 │                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Field | Behavior | Why |
|-------|----------|-----|
| `systemTokens` | **CONSTANT** | Same system prompt + tool definitions for all calls |
| `userTokens` | **CONSTANT** | Same user message triggered all calls in this turn |
| `assistantTokens` | **GROWS** | Model's intermediate responses accumulate |
| `toolResultTokens` | **GROWS** | Tool outputs accumulate with each tool call |

**Query:** Run `49_single_turn_with_truncation.kql` to see this pattern in your data.

---

## 5. Copilot Estimates vs Actual API Tokens

### The Token Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  STAGE 1: COPILOT PREPARES (BEFORE API call)                                │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  Copilot Extension                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  1. Build message list: [system, user, assistant, tool...]          │   │
│  │                                                                      │   │
│  │  2. ESTIMATE token counts using FAST tokenizer                      │   │
│  │     (Not the real model tokenizer - that's too slow!)               │   │
│  │                                                                      │   │
│  │  3. Check: Will this fit in maxTokenWindow?                         │   │
│  │     - If yes → send all                                              │   │
│  │     - If no → truncate older messages                               │   │
│  │                                                                      │   │
│  │  4. Log telemetry (INPUT direction):                                │   │
│  │     messagesJson = [{role:"system", content:14722}, ...]            │   │
│  │                      ↑ These are ESTIMATES, not actual counts!       │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│  STAGE 2: LLM API PROCESSES (AFTER API call)                                │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  Claude / GPT-4 / Gemini                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                      │   │
│  │  1. Receive messages from Copilot                                   │   │
│  │                                                                      │   │
│  │  2. Tokenize using MODEL'S OWN tokenizer                            │   │
│  │     (Different from Copilot's estimate!)                            │   │
│  │                                                                      │   │
│  │  3. Process and generate response                                    │   │
│  │                                                                      │   │
│  │  4. Return ACTUAL token counts:                                     │   │
│  │     promptTokens = 51,741  ← This is what you're CHARGED           │   │
│  │     completionTokens = 500                                          │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│  RESULT: TWO DIFFERENT NUMBERS!                                             │
│                                                                             │
│  trajectoryTotal = 110,753  (Copilot's ESTIMATE)                           │
│  promptTokens    =  51,741  (Claude's ACTUAL count)                        │
│                                                                             │
│  tokenizerRatio = 51,741 / 110,753 = 0.47                                  │
│  → Claude counted only 47% of what Copilot estimated!                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why the Difference?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  SAME TEXT, DIFFERENT TOKENIZERS = DIFFERENT COUNTS                         │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  Text: "Hello, how are you doing today?"                                    │
│                                                                             │
│  ┌─────────────────────────┐    ┌─────────────────────────┐                │
│  │  Copilot's Tokenizer    │    │  Claude's Tokenizer     │                │
│  │  ───────────────────────│    │  ───────────────────────│                │
│  │  "Hello" → 1 token      │    │  "Hello," → 1 token     │                │
│  │  "," → 1 token          │    │  " how" → 1 token       │                │
│  │  " how" → 1 token       │    │  " are you" → 1 token   │                │
│  │  " are" → 1 token       │    │  " doing" → 1 token     │                │
│  │  " you" → 1 token       │    │  " today?" → 1 token    │                │
│  │  " doing" → 1 token     │    │                         │                │
│  │  " today" → 1 token     │    │  TOTAL: 5 tokens        │                │
│  │  "?" → 1 token          │    │                         │                │
│  │                         │    │                         │                │
│  │  TOTAL: 8 tokens        │    │                         │                │
│  └─────────────────────────┘    └─────────────────────────┘                │
│                                                                             │
│  Same text, different tokenizers, different counts!                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Context Truncation

### When Does Truncation Happen?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  TRUNCATION OCCURS WHEN: trajectoryTotal > maxTokenWindow                   │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│                                                                             │
│  NO TRUNCATION (fits in window):                                            │
│  ────────────────────────────────                                           │
│                                                                             │
│  maxTokenWindow = 128,000                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│                        │  │
│  │ trajectoryTotal = 55,000                   │     unused space       │  │
│  │ (all messages fit!)                        │                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  exceededWindow = FALSE ✓                                                   │
│                                                                             │
│                                                                             │
│  TRUNCATION (exceeds window):                                               │
│  ────────────────────────────                                               │
│                                                                             │
│  maxTokenWindow = 128,000                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │████████████████████████████████████████████████████████████████████│  │
│  │ trajectoryTotal = 195,000                                           │  │
│  │ (67,000 tokens DROPPED!)                                            │──┼──┐
│  └──────────────────────────────────────────────────────────────────────┘  │  │
│                                                                             │  │
│                                                    ┌────────────────────┐  │  │
│                                                    │  DROPPED (67K):    │◀─┘  │
│                                                    │  - Old tool results│     │
│                                                    │  - Old assistant   │     │
│                                                    │    responses       │     │
│                                                    └────────────────────┘     │
│                                                                             │
│  exceededWindow = TRUE ⚠️                                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### How to Detect Truncation (CORRECT vs WRONG)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ✅ CORRECT: Use exceededWindow                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  exceededWindow = trajectoryTotal > maxTokenWindow                          │
│                                                                             │
│  - TRUE  → Context exceeded window → Truncation GUARANTEED                  │
│  - FALSE → Context fit in window → NO truncation                            │
│                                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  ❌ WRONG: Using truncationDelta                                            │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  truncationDelta = trajectoryTotal - promptTokens                           │
│                  = Copilot estimate - API actual                            │
│                  = TOKENIZER DIFFERENCE (not truncation!)                   │
│                                                                             │
│  Example from real data:                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  trajectoryTotal = 110,753                                          │   │
│  │  maxTokenWindow  = 127,997                                          │   │
│  │  promptTokens    =  51,741                                          │   │
│  │                                                                      │   │
│  │  truncationDelta = 110,753 - 51,741 = 59,012  ← LARGE number!       │   │
│  │                                                                      │   │
│  │  But wait...                                                         │   │
│  │  110,753 < 127,997 → Context FIT in window!                         │   │
│  │                                                                      │   │
│  │  exceededWindow = FALSE → NO TRUNCATION                              │   │
│  │                                                                      │   │
│  │  The 59K delta is just tokenizer mismatch, NOT truncation!          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What Gets Dropped During Truncation?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  MULTI-TURN CONVERSATION WITH TRUNCATION                                    │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  TURN 1 (messageId: msg-001)                                                │
│  ├── LLM Call 1-4: User asks, model uses tools                             │
│  └── Accumulated: 35K tokens of tool results                               │
│                                                                             │
│  TURN 2 (messageId: msg-002)                                                │
│  ├── LLM Call 1-3: Follow-up question, more tools                          │
│  └── Accumulated: +25K tokens (total now 60K)                              │
│                                                                             │
│  TURN 3 (messageId: msg-003)  ← CURRENT TURN                                │
│  ├── LLM Call 1: User asks complex question                                │
│  ├── LLM Call 2: read_file → +50K tokens                                   │
│  ├── LLM Call 3: run_terminal → +30K tokens                                │
│  ├── LLM Call 4: read_file → +40K tokens                                   │
│  │                                                                          │
│  │   TOTAL CONTEXT NOW:                                                     │
│  │   ┌─────────────────────────────────────────────────────────────────┐   │
│  │   │  system (14K)                                                    │   │
│  │   │  + Turn 1 (35K)                                                  │   │
│  │   │  + Turn 2 (25K)                                                  │   │
│  │   │  + Turn 3 so far (120K)                                          │   │
│  │   │  ─────────────────                                               │   │
│  │   │  = 194K total                                                    │   │
│  │   │                                                                  │   │
│  │   │  But maxTokenWindow = 128K!                                      │   │
│  │   └─────────────────────────────────────────────────────────────────┘   │
│  │                                                                          │
│  │   ┌─────────────────────────────────────────────────────────────────┐   │
│  │   │                    TRUNCATION HAPPENS                            │   │
│  │   │                                                                  │   │
│  │   │  ┌────────────────────┐  ┌──────────────────────────────────┐   │   │
│  │   │  │ DROPPED (66K):     │  │ KEPT (128K):                     │   │   │
│  │   │  │                    │  │                                   │   │   │
│  │   │  │ • Turn 1 tool      │  │ • System prompt (14K) ← ALWAYS   │   │   │
│  │   │  │   results (35K)    │  │ • Turn 3 user message            │   │   │
│  │   │  │                    │  │ • Recent tool results            │   │   │
│  │   │  │ • Turn 2 tool      │  │ • Recent assistant responses     │   │   │
│  │   │  │   results (25K)    │  │                                   │   │   │
│  │   │  │                    │  │ (Most recent content preserved)  │   │   │
│  │   │  │ • Turn 3 early     │  │                                   │   │   │
│  │   │  │   results (6K)     │  │                                   │   │   │
│  │   │  └────────────────────┘  └──────────────────────────────────┘   │   │
│  │   │         ↑                          ↑                            │   │
│  │   │    FROM PREVIOUS              FROM CURRENT                      │   │
│  │   │    TURNS + EARLIER            TURN (recent)                     │   │
│  │   │    IN SAME TURN                                                 │   │
│  │   └─────────────────────────────────────────────────────────────────┘   │
│  │                                                                          │
│  ├── LLM Call 5: (with truncated context) model continues...               │
│  └── ...                                                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Insight:** Truncation can drop content from:
1. **Previous turns** (oldest first)
2. **Earlier LLM calls within the SAME turn** (if the turn is very long)

**Query:** Run `49_single_turn_with_truncation.kql` to detect truncation in your data.

---

## 7. System Tokens Across Turns and Conversations

### Does `systemTokens` vary across turns in the same conversation?

**Query:** `50_verify_system_across_turns.kql`

From empirical testing, `systemTokens` is **constant within a conversation**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SAME CONVERSATION (4 turns)                                                │
│                                                                             │
│  turnIndex │ messageId                              │ systemTokens │        │
│  ══════════╪════════════════════════════════════════╪══════════════╪════════│
│      1     │ ce246918-e14b-40c5-8470-9bef131805aa   │    6,274     │  SAME  │
│      2     │ cb1155ac-74ed-4049-9228-fd9e821b6ff7   │    6,274     │  SAME  │
│      3     │ 5c095f4d-192d-4f5e-b2a5-01926aab1f46   │    6,274     │  SAME  │
│      4     │ aa521ced-00f3-4e69-804f-2a9bc42ca871   │    6,274     │  SAME  │
│                                                                             │
│  System prompt is constant within a conversation!                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Does `systemTokens` vary across different conversations?

**Query:** `51_verify_system_across_conversations.kql`

From empirical testing, there is **HIGH variance** across conversations:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ACROSS DIFFERENT CONVERSATIONS (by model)                                  │
│                                                                             │
│  model              │ conversations │ avgSystem │ minSystem │ maxSystem │   │
│  ═══════════════════╪═══════════════╪═══════════╪═══════════╪═══════════╪═══│
│  claude-sonnet-4.5  │     541       │  15,486   │   5,793   │  157,952  │   │
│  claude-opus-4.5    │     282       │  17,902   │       0   │  149,177  │   │
│  gemini-3-pro       │      72       │  14,681   │       0   │   52,957  │   │
│  claude-haiku-4.5   │      35       │  20,309   │   7,048   │  224,983  │   │
│  gpt-4.1            │      18       │  14,496   │   8,143   │   31,214  │   │
│                                                                             │
│  Reasons for variance:                                                      │
│  • Different tool sets enabled                                              │
│  • A/B experiment flags                                                     │
│  • Workspace-specific context                                               │
│  • Model-specific system prompts                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Token Fields Reference

| Field | Source | Event Direction | Description |
|-------|--------|-----------------|-------------|
| `promptTokens` | LLM API | OUTPUT | **Actual** tokens charged. Use for cost analysis. |
| `completionTokens` | LLM API | OUTPUT | **Actual** response tokens from the model. |
| `maxTokenWindow` | Model config | OUTPUT | Maximum context window for the model. |
| `trajectoryTotal` | Copilot estimate | INPUT | Sum of all role token estimates. |
| `systemTokens` | Copilot estimate | INPUT | System prompt + tool definitions. |
| `userTokens` | Copilot estimate | INPUT | User's message tokens. |
| `assistantTokens` | Copilot estimate | INPUT | Model's previous responses in context. |
| `toolResultTokens` | Copilot estimate | INPUT | Tool output tokens accumulated so far. |
| `exceededWindow` | Calculated | - | `trajectoryTotal > maxTokenWindow` (truncation indicator) |
| `tokenizerRatio` | Calculated | - | `promptTokens / trajectoryTotal` (tokenizer difference) |

---

## 9. Telemetry Events Reference

### `engine.messages.length` (INPUT direction)
- **When**: Before sending to LLM API
- **Contains**: `messagesJson` with token ESTIMATES per role
- **Example**: `{role:"system", content:14722}` where content = token count estimate

### `engine.messages.length` (OUTPUT direction)
- **When**: After receiving from LLM API
- **Contains**: Actual token counts from the API
- **Fields**: `promptTokens`, `completionTokens`, `maxTokenWindow`

### `toolCallDetailsInternal`
- **When**: After turn completes
- **Contains**: Tool usage summary for the turn
- **Fields**: `messageId`, `turnIndex`, `numRequests`, `toolCounts`, `turnDuration`

### `conversation.messageText`
- **When**: After each message
- **Contains**: Actual text content (user or model)
- **Fields**: `messageId`, `source` (user/model), `messageText`

---

## 10. Related Exploration Queries

| Query File | Purpose |
|------------|---------|
| `47_single_turn_with_tools.kql` | Basic token breakdown for a single turn |
| `48_find_messageid_with_tools.kql` | Find messageIds with tool usage |
| `49_single_turn_with_truncation.kql` | **Full breakdown + truncation detection** |
| `50_verify_system_across_turns.kql` | Check if systemTokens varies within conversation |
| `51_verify_system_across_conversations.kql` | Check if systemTokens varies across conversations |
