# GitHub Copilot Token Data Schema

This document explains how tokens are tracked in GitHub Copilot (VS Code) agent mode telemetry.

**Related Queries:**
- `exploration/token_mechanics/49_single_turn_with_truncation.kql` — Full token breakdown with truncation detection
- `exploration/token_mechanics/50_verify_system_across_turns.kql` — Verify system tokens across turns
- `exploration/token_mechanics/51_verify_system_across_conversations.kql` — Verify system tokens across conversations

---

## Data Schema Overview

Copilot telemetry captures two distinct perspectives on token usage: **estimates** computed client-side before the API call, and **actuals** returned by the LLM after processing. Understanding this distinction is critical for accurate analysis.

### Token Fields Reference

| Field | Source | Direction | Description |
|-------|--------|-----------|-------------|
| `promptTokens` | LLM API | OUTPUT | Actual tokens charged — use for cost analysis |
| `completionTokens` | LLM API | OUTPUT | Actual response tokens from the model |
| `maxTokenWindow` | Model config | OUTPUT | Maximum context window for the model |
| `trajectoryTotal` | Copilot | INPUT | Sum of all role token estimates |
| `systemTokens` | Copilot | INPUT | System prompt + tool definitions |
| `userTokens` | Copilot | INPUT | User's message tokens |
| `assistantTokens` | Copilot | INPUT | Model's previous responses in context |
| `toolResultTokens` | Copilot | INPUT | Tool output tokens accumulated so far |
| `exceededWindow` | Calculated | — | `trajectoryTotal > maxTokenWindow` (truncation flag) |
| `tokenizerRatio` | Calculated | — | `promptTokens / trajectoryTotal` (tokenizer difference) |

### Visual Schema

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOKEN DATA FLOW                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   COPILOT CLIENT (INPUT)              LLM API (OUTPUT)                      │
│   ══════════════════════              ════════════════                      │
│                                                                             │
│   ┌─────────────────────┐             ┌─────────────────────┐              │
│   │  ESTIMATES          │             │  ACTUALS            │              │
│   │  ─────────────────  │   ──────▶   │  ─────────────────  │              │
│   │  systemTokens       │   API Call  │  promptTokens       │              │
│   │  userTokens         │             │  completionTokens   │              │
│   │  assistantTokens    │             │  maxTokenWindow     │              │
│   │  toolResultTokens   │             │                     │              │
│   │  ─────────────────  │             └─────────────────────┘              │
│   │  trajectoryTotal    │                                                   │
│   └─────────────────────┘                                                   │
│                                                                             │
│   Fast client tokenizer               Model's actual tokenizer              │
│   (for truncation decisions)          (for billing/limits)                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Telemetry Events

**`engine.messages.length` (INPUT direction)**  
Captured before sending to the LLM API. Contains `messagesJson` with token estimates per role (e.g., `{role:"system", content:14722}` where `content` = estimated token count).

**`engine.messages.length` (OUTPUT direction)**  
Captured after receiving the API response. Contains actual token counts: `promptTokens`, `completionTokens`, `maxTokenWindow`.

**`toolCallDetailsInternal`**  
Captured after a turn completes. Summarizes tool usage: `messageId`, `turnIndex`, `numRequests`, `toolCounts`, `turnDuration`.

**`conversation.messageText`**  
Captured after each message. Contains actual text content: `messageId`, `source` (user/model), `messageText`.

---

## Key Concepts

### What Is a "Trajectory"?

A trajectory is the complete list of messages sent to the LLM at a given moment — essentially a snapshot of the conversation context for each API call.

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

The `hasTrajectory` field indicates whether the INPUT telemetry event was captured with `messagesJson` populated. When `false`, you only have `promptTokens` from the OUTPUT event.

### Token Behavior Within a Turn

A **turn** begins when the user sends a message and may involve multiple LLM calls as the model uses tools. All calls within a turn share the same `messageId`.

| Field | Behavior | Why |
|-------|----------|-----|
| `systemTokens` | **Constant** | Same system prompt + tool definitions |
| `userTokens` | **Constant** | Same user message triggered all calls |
| `assistantTokens` | **Grows** | Model's intermediate responses accumulate |
| `toolResultTokens` | **Grows** | Tool outputs accumulate with each call |

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TOKEN BEHAVIOR WITHIN A TURN (9 LLM calls)                                 │
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
│            │   CONSTANT   │  CONSTANT  │     GROWS       │     GROWS        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Query:** Run `49_single_turn_with_truncation.kql` to observe this pattern.

---

## Common Questions

### Why is `promptTokens` already 25K for the first message?

Tool definitions are always included in the system message, even before any tool is invoked. This creates a baseline cost of ~12–20K tokens just for tool availability.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FIRST LLM CALL — BEFORE ANY TOOLS ARE USED                                 │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  SYSTEM PROMPT                                            ~3,000 tokens│ │
│  │  "You are a helpful coding assistant..."                              │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  TOOL DEFINITIONS (JSON Schemas)              ~8,000–12,000 tokens    │ │
│  │                                                                        │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │
│  │  │  read_file   │ │  write_file  │ │ grep_search  │ │ run_terminal │ │ │
│  │  │  ~400 tokens │ │  ~400 tokens │ │  ~350 tokens │ │  ~500 tokens │ │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ │ │
│  │                                                                        │ │
│  │  ← You pay for tool AVAILABILITY even if tools are never used →       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  USER MESSAGE                                        ~100–5,000 tokens │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  TOTAL BASELINE: ~12,000–20,000 tokens BEFORE any tool invocation          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why is `userTokens` constant across all LLM calls in a turn?

All LLM calls within a turn share the same `messageId` because they were triggered by one user message. The user sent one request; the model makes multiple calls to fulfill it.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  USER SENDS ONE MESSAGE                                                     │
│                                                                             │
│  "Please read my config file and run the tests"                            │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  TURN BEGINS (messageId: abc-123)                                   │   │
│  │                                                                      │   │
│  │  LLM Call 1: "I'll read the config file..." → calls read_file       │   │
│  │  LLM Call 2: "I see the config. Now running tests..." → run_terminal│   │
│  │  LLM Call 3: "Tests complete! Here are the results..." → final      │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  All 3 LLM calls share the SAME user message = SAME userTokens             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why do `trajectoryTotal` and `promptTokens` differ?

Copilot uses a fast client-side tokenizer to estimate counts for truncation decisions. The LLM uses its own tokenizer, which produces different counts. The same text tokenizes differently depending on the algorithm.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SAME TEXT, DIFFERENT TOKENIZERS                                            │
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
│  │  TOTAL: 8 tokens        │    │                         │                │
│  └─────────────────────────┘    └─────────────────────────┘                │
│                                                                             │
│  tokenizerRatio = 5/8 = 0.625 (Claude counted 63% of Copilot's estimate)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Important:** A large difference between `trajectoryTotal` and `promptTokens` does not indicate truncation — it reflects tokenizer mismatch. Use `exceededWindow` to detect truncation.

---

## Context Truncation

### When Does Truncation Occur?

Truncation happens when `trajectoryTotal > maxTokenWindow`. Copilot drops older messages to fit within the model's context limit.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  NO TRUNCATION (fits in window)                                             │
│                                                                             │
│  maxTokenWindow = 128,000                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│                        │  │
│  │ trajectoryTotal = 55,000                   │     unused space       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│  exceededWindow = FALSE ✓                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  TRUNCATION (exceeds window)                                                │
│                                                                             │
│  maxTokenWindow = 128,000                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │████████████████████████████████████████████████████████████████████│  │
│  │ trajectoryTotal = 195,000 (67,000 tokens DROPPED!)                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│  exceededWindow = TRUE ⚠️                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Detecting Truncation Correctly

✅ **Correct:** Use `exceededWindow = trajectoryTotal > maxTokenWindow`

❌ **Wrong:** Using `truncationDelta = trajectoryTotal - promptTokens` — this measures tokenizer difference, not truncation.

```
Example from real data:
  trajectoryTotal = 110,753
  maxTokenWindow  = 127,997
  promptTokens    =  51,741
  
  truncationDelta = 59,012 ← Large number, but NOT truncation!
  
  110,753 < 127,997 → Context FIT in window
  exceededWindow = FALSE → NO TRUNCATION
  
  The 59K delta is tokenizer mismatch, not dropped content.
```

### What Gets Dropped?

Truncation removes content in order of age: oldest turns first, then earlier content within the current turn. The system prompt is always preserved.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TRUNCATION PRIORITY                                                        │
│                                                                             │
│  ┌────────────────────┐    ┌──────────────────────────────────┐            │
│  │ DROPPED FIRST:     │    │ KEPT:                            │            │
│  │                    │    │                                   │            │
│  │ • Old turn tool    │    │ • System prompt (always kept)    │            │
│  │   results          │    │ • Current user message           │            │
│  │ • Old turn         │    │ • Recent tool results            │            │
│  │   assistant msgs   │    │ • Recent assistant responses     │            │
│  │ • Earlier content  │    │                                   │            │
│  │   in current turn  │    │ (Most recent content preserved)  │            │
│  └────────────────────┘    └──────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Query:** Run `49_single_turn_with_truncation.kql` to detect truncation in your data.

---

## System Tokens Behavior

### Across Turns (Same Conversation)

`systemTokens` remains **constant** within a conversation — the same system prompt and tool definitions are used throughout.

**Query:** `50_verify_system_across_turns.kql`

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
└─────────────────────────────────────────────────────────────────────────────┘
```

### Across Conversations

`systemTokens` shows **high variance** across different conversations due to different tool sets, A/B experiments, workspace context, and model-specific prompts.

**Query:** `51_verify_system_across_conversations.kql`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ACROSS DIFFERENT CONVERSATIONS (by model)                                  │
│                                                                             │
│  model              │ conversations │ avgSystem │ minSystem │ maxSystem    │
│  ═══════════════════╪═══════════════╪═══════════╪═══════════╪══════════════│
│  claude-sonnet-4.5  │     541       │  15,486   │   5,793   │  157,952     │
│  claude-opus-4.5    │     282       │  17,902   │       0   │  149,177     │
│  gemini-3-pro       │      72       │  14,681   │       0   │   52,957     │
│  claude-haiku-4.5   │      35       │  20,309   │   7,048   │  224,983     │
│  gpt-4.1            │      18       │  14,496   │   8,143   │   31,214     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Related Queries

| Query File | Purpose |
|------------|---------|
| `47_single_turn_with_tools.kql` | Basic token breakdown for a single turn |
| `48_find_messageid_with_tools.kql` | Find messageIds with tool usage |
| `49_single_turn_with_truncation.kql` | Full breakdown + truncation detection |
| `50_verify_system_across_turns.kql` | Verify systemTokens within a conversation |
| `51_verify_system_across_conversations.kql` | Verify systemTokens across conversations |
