# Part 1: Understanding the Data Structure

This document explains the hierarchical structure of agent mode conversations in telemetry, using a real conversation example.

---

## 1.1 Sample Complete Conversation

Below is a **complete 3-turn conversation** extracted from telemetry. We'll use this to explain every field.

> **Query Reference:** This sample was generated using  
> [`exploration/complete_3turn_conversations_with_delta.kql`](../exploration/complete_3turn_conversations_with_delta.kql)  
> For production use with 3-10 turn conversations, see:  
> [`production/sft_complete_conversations_3to10.kql`](../production/sft_complete_conversations_3to10.kql)

```json
{
  "conversationId": "abc123-example",
  "userName": "developer_microsoft",
  "capturedTurnCount": 3,
  "minTurnIndex": 1,
  "maxTurnIndex": 3,
  "isComplete": true,
  "turns": [
    {
      "turnIndex": 1,
      "messageId": "1ab2371f-dc75-4e16-88b3-03a3ee551afe",
      "userMessage": "What is the simplest way to spin up a Slack API client?",
      "modelMessage": "Here's the simplest approach for your custom local Slack front-end... [detailed response with code]",
      "llmCalls": [
        { "promptTokens": 11317, "completionTokens": 113, "model": "claude-opus-4.5" },
        { "promptTokens": 15817, "completionTokens": 177, "model": "claude-opus-4.5" },
        { "promptTokens": 18210, "completionTokens": 92,  "model": "claude-opus-4.5" },
        { "promptTokens": 21934, "completionTokens": 915, "model": "claude-opus-4.5" }
      ],
      "turnToolTokens": 37733,
      "turnToolCount": 3,
      "toolCounts": "{\"mcp_web-search_web_search\":2,\"mcp_web-search_web_fetch\":1}",
      "numRequests": 4,
      "turnDurationMs": 48152
    },
    {
      "turnIndex": 2,
      "messageId": "37518f4c-21a2-4bb0-8f4e-e955b8bb513c",
      "userMessage": "I went to /apps site and clicked Create an app...",
      "modelMessage": "I see you're on the 'Your Apps' page... Click the green 'Create an App' button...",
      "llmCalls": [
        { "promptTokens": 24426, "completionTokens": 299, "model": "claude-opus-4.5" }
      ],
      "turnToolTokens": 37733,
      "turnToolCount": 3,
      "toolCounts": "{}",
      "numRequests": 1,
      "turnDurationMs": 10646
    },
    {
      "turnIndex": 3,
      "messageId": "3e149ef8-5733-46f4-ab92-b14571996df7",
      "userMessage": "Who will have access to this app? I'd like to lock it down to just me...",
      "modelMessage": "Great security question! Only YOU - when you create a personal Slack app...",
      "llmCalls": [
        { "promptTokens": 24989, "completionTokens": 466, "model": "claude-opus-4.5" }
      ],
      "turnToolTokens": 37733,
      "turnToolCount": 3,
      "toolCounts": "{}",
      "numRequests": 1,
      "turnDurationMs": 15818
    }
  ]
}
```

---

## 1.2 Visual: Conversation Hierarchy

<!-- DIAGRAM PLACEHOLDER: conversation_hierarchy.svg -->

### ASCII Representation

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CONVERSATION                                        │
│                     conversationId: "abc123-example"                            │
│                                                                                  │
│  A conversation is one chat session. Press "+" in VS Code = new conversation.   │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  TURN 1  (turnIndex: 1, messageId: "1ab2371f...")                          │ │
│  │                                                                             │ │
│  │  ┌─────────────────────┐                                                   │ │
│  │  │  👤 USER TURN       │  "What is the simplest way to spin up            │ │
│  │  │  (1 message)        │   a Slack API client?"                           │ │
│  │  └─────────────────────┘                                                   │ │
│  │            │                                                                │ │
│  │            ▼                                                                │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │  🤖 MODEL TURN (with tool use) - 4 LLM calls                        │   │ │
│  │  │                                                                      │   │ │
│  │  │  LLM Call 1: "I'll search for Slack API docs..."                    │   │ │
│  │  │       ↓ [tool: web_search] → result added to context                │   │ │
│  │  │  LLM Call 2: "Found some info, let me search more..."               │   │ │
│  │  │       ↓ [tool: web_search] → result added to context                │   │ │
│  │  │  LLM Call 3: "Let me fetch the official page..."                    │   │ │
│  │  │       ↓ [tool: web_fetch] → result added to context                 │   │ │
│  │  │  LLM Call 4: "Here's the simplest approach..." (FINAL RESPONSE)     │   │ │
│  │  │                                                                      │   │ │
│  │  │  numRequests: 4  |  toolCounts: {web_search:2, web_fetch:1}         │   │ │
│  │  └─────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  TURN 2  (turnIndex: 2, messageId: "37518f4c...")                          │ │
│  │                                                                             │ │
│  │  ┌─────────────────────┐                                                   │ │
│  │  │  👤 USER TURN       │  "I went to /apps site and clicked Create..."    │ │
│  │  └─────────────────────┘                                                   │ │
│  │            │                                                                │ │
│  │            ▼                                                                │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │  🤖 MODEL TURN (text only) - 1 LLM call                             │   │ │
│  │  │                                                                      │   │ │
│  │  │  LLM Call 1: "I see you're on the 'Your Apps' page..." (FINAL)      │   │ │
│  │  │                                                                      │   │ │
│  │  │  numRequests: 1  |  toolCounts: {}                                  │   │ │
│  │  └─────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  TURN 3  (turnIndex: 3, messageId: "3e149ef8...")                          │ │
│  │                                                                             │ │
│  │  ┌─────────────────────┐                                                   │ │
│  │  │  👤 USER TURN       │  "Who will have access to this app?..."          │ │
│  │  └─────────────────────┘                                                   │ │
│  │            │                                                                │ │
│  │            ▼                                                                │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │ │
│  │  │  🤖 MODEL TURN (text only) - 1 LLM call                             │   │ │
│  │  │                                                                      │   │ │
│  │  │  LLM Call 1: "Great security question! Only YOU..." (FINAL)         │   │ │
│  │  │                                                                      │   │ │
│  │  │  numRequests: 1  |  toolCounts: {}                                  │   │ │
│  │  └─────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1.3 Field Definitions (Conversation Level)

| Field | Type | Example | Definition |
|-------|------|---------|------------|
| `conversationId` | string | `"abc123-example"` | Unique identifier for the entire chat session. New "+" button in VS Code = new conversationId. |
| `userName` | string | `"developer_microsoft"` | Anonymized user identifier from telemetry. |
| `capturedTurnCount` | int | `3` | Number of turns actually captured in this query result. |
| `minTurnIndex` | int | `1` | Lowest turnIndex in the captured data. If `1`, we have the conversation start. |
| `maxTurnIndex` | int | `3` | Highest turnIndex in the captured data. |
| `isComplete` | bool | `true` | Flag indicating completeness: `minTurnIndex == 1 AND capturedTurnCount == maxTurnIndex`. |
| `turns` | array | `[...]` | Array of turn objects, ordered by turnIndex. |

### Completeness Formula

```
isComplete = (minTurnIndex == 1) AND (capturedTurnCount == maxTurnIndex)
```

| minTurnIndex | maxTurnIndex | capturedTurnCount | isComplete | Why |
|--------------|--------------|-------------------|------------|-----|
| 1 | 3 | 3 | ✅ true | Starts at 1, no gaps |
| 1 | 5 | 4 | ❌ false | Gap detected (5-1+1=5 ≠ 4) |
| 50 | 55 | 6 | ❌ false | Missing turns 1-49 |

---

## 1.4 Field Definitions (Turn Level)

### Core Turn Fields

| Field | Type | Example | Definition |
|-------|------|---------|------------|
| `turnIndex` | int | `1` | Sequential turn number within conversation. **1-indexed** (starts at 1, not 0). |
| `messageId` | string | `"1ab2371f-..."` | Unique identifier for this turn. Also known as `headerRequestId` in some events. |
| `userMessage` | string | `"What is..."` | The user's input text that initiated this turn. **Always exactly 1 per turn.** |
| `modelMessage` | string | `"Here's..."` | The model's final response text. May be summarized from multiple intermediate responses. |

### What is a Turn?

A **turn** is one user query plus all model activity to respond to it.

```
TURN = 1 User Message + N LLM Calls (where N ≥ 1)
```

The model may make **multiple LLM API calls** within a single turn:
- **Tool-use calls**: Model decides to call a tool, waits for result
- **Final response call**: Model produces the final answer (no tool call)

---

## 1.5 Understanding llmCalls Array

### What is an LLM Call?

Each element in `llmCalls` represents **one LLM API request-response cycle**. This is raw telemetry data.

```
Turn 1 llmCalls (from our example):
┌─────────────────────────────────────────────────────────────────────────────┐
│  llmCalls[0]: { promptTokens: 11317, completionTokens: 113 }               │
│               Model decides to search → calls web_search tool              │
│                                                                             │
│  llmCalls[1]: { promptTokens: 15817, completionTokens: 177 }               │
│               Model decides to search again → calls web_search tool        │
│               (promptTokens increased by ~4500 = tool result added)        │
│                                                                             │
│  llmCalls[2]: { promptTokens: 18210, completionTokens: 92 }                │
│               Model decides to fetch page → calls web_fetch tool           │
│               (promptTokens increased by ~2400 = tool result added)        │
│                                                                             │
│  llmCalls[3]: { promptTokens: 21934, completionTokens: 915 }               │
│               Model produces FINAL RESPONSE (no tool call)                 │
│               (promptTokens increased by ~3700 = tool result added)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### llmCalls Field Definitions

| Field | Type | Example | Definition |
|-------|------|---------|------------|
| `promptTokens` | int | `21934` | **CUMULATIVE** context tokens sent to the LLM for this call. Includes system prompt + conversation history + all tool results so far. |
| `completionTokens` | int | `915` | Tokens in the model's output for this specific call. Unique per call (not cumulative). |
| `model` | string | `"claude-opus-4.5"` | Which model handled this LLM call. |

---

## 1.6 Understanding promptTokens (CUMULATIVE)

**Critical concept:** `promptTokens` is **cumulative by nature**. Each LLM call re-sends the entire context.

### Visual: Token Growth Within a Turn

```
Turn 1: User asks about Slack API
─────────────────────────────────────────────────────────────────────────────

LLM Call 1:
┌─────────────────────────────────────────────────────────────────┐
│  PROMPT (11,317 tokens)                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  System prompt          (~3,000 tokens)                 │   │
│  │  Conversation history   (0 tokens - first turn)         │   │
│  │  User message           (~200 tokens)                   │   │
│  │  Available tools        (~8,000 tokens)                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼  Model calls web_search tool → gets result (~4,500 tokens)
         
LLM Call 2:
┌─────────────────────────────────────────────────────────────────┐
│  PROMPT (15,817 tokens)  ← GREW by ~4,500                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Everything from Call 1                 (11,317 tokens) │   │
│  │  + Tool call request                    (~50 tokens)    │   │
│  │  + Tool result from web_search          (~4,450 tokens) │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼  Model calls web_search again → gets result (~2,400 tokens)

LLM Call 3:
┌─────────────────────────────────────────────────────────────────┐
│  PROMPT (18,210 tokens)  ← GREW by ~2,400                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Everything from Call 2                 (15,817 tokens) │   │
│  │  + Tool call request                    (~50 tokens)    │   │
│  │  + Tool result from web_search          (~2,350 tokens) │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼  Model calls web_fetch → gets result (~3,700 tokens)

LLM Call 4 (FINAL):
┌─────────────────────────────────────────────────────────────────┐
│  PROMPT (21,934 tokens)  ← GREW by ~3,700                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Everything from Call 3                 (18,210 tokens) │   │
│  │  + Tool call request                    (~50 tokens)    │   │
│  │  + Tool result from web_fetch           (~3,650 tokens) │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  → Model produces final response (915 completion tokens)        │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Matters

- Each LLM call includes **ALL** previous context
- `promptTokens` grows with each tool result added
- This is the **actual token cost** for each API call
- **NOT** an incremental count - it's the full context each time

---

## 1.7 Understanding promptTokenDelta (CALCULATED)

`promptTokenDelta` is a **calculated field** (not raw from telemetry) that shows what was added between LLM calls.

### Calculation

```
promptTokenDelta[0] = promptTokens[0]                    // First call = full context
promptTokenDelta[n] = promptTokens[n] - promptTokens[n-1]  // Subsequent = difference
```

### Example from Turn 1

| LLM Call | promptTokens | promptTokenDelta | What Was Added |
|----------|--------------|------------------|----------------|
| 0 | 11,317 | **11,317** | Initial context (system + user + tools) |
| 1 | 15,817 | **4,500** | web_search result #1 |
| 2 | 18,210 | **2,393** | web_search result #2 |
| 3 | 21,934 | **3,724** | web_fetch result |

### ⚠️ Important: Only Reliable for Complete Conversations

`promptTokenDelta` is **only meaningful** when the conversation is complete (`isComplete: true`).

**Why?**

For partial captures (e.g., we only captured turns 50-55 of a 100-turn conversation):
- Turn 50 appears as "first" turn in our data
- Its `promptTokenDelta` = full `promptTokens` (e.g., 150,000)
- But the **actual** delta from Turn 49 might have been only 2,000
- We don't have Turn 49's data to calculate the true delta!

```
PARTIAL CAPTURE PROBLEM:
─────────────────────────────────────────────────────────────────
Full conversation:  Turn 1 → Turn 2 → ... → Turn 49 → Turn 50 → Turn 51
                                                │         │
                                           (missing)     │
                                                         ▼
Captured data:                                      Turn 50 → Turn 51

Turn 50 in our data:
  promptTokens = 150,000
  promptTokenDelta = 150,000  ← INFLATED! Actual delta was ~2,000
```

**Solution:** Filter for `isComplete: true` to ensure reliable deltas.

---

## 1.8 Tool-Related Fields

### Fields in Output

| Field | Type | Example | Definition |
|-------|------|---------|------------|
| `toolCounts` | string (JSON) | `"{\"web_search\":2,\"web_fetch\":1}"` | Which tools were called and how many times in this turn. |
| `numRequests` | int | `4` | Total LLM API calls in this turn. Formula: `sum(toolCounts) + 1` |
| `turnToolTokens` | int | `37733` | Sum of tokens from tool results in THIS turn only. |
| `turnToolCount` | int | `3` | Number of tool results processed in THIS turn. |

### The numRequests Formula

```
numRequests = sum(values in toolCounts) + 1
```

| toolCounts | sum | +1 | numRequests | Explanation |
|------------|-----|----|-------------|-------------|
| `{}` | 0 | +1 | **1** | Text-only response (no tools) |
| `{web_search:1}` | 1 | +1 | **2** | 1 tool + final response |
| `{web_search:2, web_fetch:1}` | 3 | +1 | **4** | 3 tools + final response |
| `{read_file:5, grep_search:3}` | 8 | +1 | **9** | 8 tools + final response |

### Visual: Model Turn Composition

```
MODEL TURN COMPOSITION
══════════════════════════════════════════════════════════════════════════

EXAMPLE: Turn with 3 tool calls (numRequests = 4)
─────────────────────────────────────────────────────────────────────────

  toolCounts: {"web_search": 2, "web_fetch": 1}
  
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                       │
  │  LLM Call 1 (Tool-use call)                                          │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  Input: [context]                                                │ │
  │  │  Output: "I'll search..." + tool_call(web_search, query="...")  │ │
  │  └─────────────────────────────────────────────────────────────────┘ │
  │       │                                                               │
  │       ▼  Tool executes → returns result                              │
  │                                                                       │
  │  LLM Call 2 (Tool-use call)                                          │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  Input: [context + tool result 1]                                │ │
  │  │  Output: "Let me search more..." + tool_call(web_search, ...)   │ │
  │  └─────────────────────────────────────────────────────────────────┘ │
  │       │                                                               │
  │       ▼  Tool executes → returns result                              │
  │                                                                       │
  │  LLM Call 3 (Tool-use call)                                          │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  Input: [context + tool results 1,2]                             │ │
  │  │  Output: "Fetching page..." + tool_call(web_fetch, url="...")   │ │
  │  └─────────────────────────────────────────────────────────────────┘ │
  │       │                                                               │
  │       ▼  Tool executes → returns result                              │
  │                                                                       │
  │  LLM Call 4 (Final response - NO tool call)                          │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  Input: [context + tool results 1,2,3]                           │ │
  │  │  Output: "Here's the simplest approach..." (final answer)       │ │
  │  └─────────────────────────────────────────────────────────────────┘ │
  │                                                                       │
  └──────────────────────────────────────────────────────────────────────┘

  TOTALS:
  ├── numRequests: 4 (3 tool calls + 1 final response)
  ├── turnToolCount: 3 (3 tool results processed)
  └── turnToolTokens: 37,733 (sum of all tool result tokens)


EXAMPLE: Turn with NO tool calls (numRequests = 1)
─────────────────────────────────────────────────────────────────────────

  toolCounts: {}
  
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                       │
  │  LLM Call 1 (Final response - text only)                             │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  Input: [context from previous turns]                            │ │
  │  │  Output: "Great security question! Only YOU..." (final answer)  │ │
  │  └─────────────────────────────────────────────────────────────────┘ │
  │                                                                       │
  └──────────────────────────────────────────────────────────────────────┘

  TOTALS:
  ├── numRequests: 1 (just the response)
  ├── turnToolCount: 0 (no tools used)
  └── turnToolTokens: 0 (no tool results)
```

---

## 1.9 Understanding Telemetry Events (Critical!)

⚠️ **IMPORTANT**: The telemetry has TWO different events with `messagesJson`, but they contain DIFFERENT data!

### The Two `messagesJson` Fields

| Event | `messagesJson` Contains | Purpose |
|-------|------------------------|---------|
| `engine.messages` | **Actual text content** | Full conversation trajectory (system prompt, user input, assistant response) |
| `engine.messages.length` | **Length metrics** | Token/character COUNT estimates per message role |

> From official Copilot data team documentation:
> "Source events: exact event `GitHub.copilot.chat/engine.messages` **(we only parse `messagesJson`, never `engine.messages.length`)**"
> — *CONVERSATION_XML_TAGS_20251001.md*

### Example Comparison

**`engine.messages.messagesJson`** (actual content):
```json
[
  {"role": "system", "content": "You are an expert AI programming assistant..."},
  {"role": "user", "content": "How do I implement a Slack API client?"},
  {"role": "assistant", "content": "Here's how you can create a Slack client..."}
]
```

**`engine.messages.length.messagesJson`** (length metrics):
```json
[
  {"role": "system", "content": 5871},
  {"role": "user", "content": 245},
  {"role": "assistant", "content": 0}
]
```

### Key Insight: Why Token Counts Don't Match

The `content` field in `engine.messages.length` is a **pre-computed estimate**, NOT the actual API token count:

| Metric | Source | Description |
|--------|--------|-------------|
| `trajectoryTotal` | Sum of `content` from `engine.messages.length` | Copilot's **estimated** tokens |
| `promptTokens` | `model.modelCall.output` | LLM API's **actual charged** tokens |

The difference is due to:
1. **Different tokenizers**: Copilot estimates vs LLM API's actual tokenization
2. **Message selection**: Not all prepared messages may be sent (context window limits)

### Snapshot vs Cumulative

From official docs:
> "Each `engine.messages` entry is a **discrete LLM API call snapshot**, not a cumulative transcript."
> — *CONVERSATION_TRAJECTORY_EXTRACTION.md*

This means each `engine.messages` event captures ONE API call's context at that moment, not the full conversation history.

### Related Documentation

See: [`docs/vscode_1p_data_team_docs/`](vscode_1p_data_team_docs/) for:
- `CONVERSATION_TRAJECTORY_EXTRACTION.md` - How trajectories are extracted
- `CONVERSATION_XML_TAGS_20251001.md` - XML tags in user messages
- `TELEMETRY_SCHEMA_20251001.md` - Full telemetry schema

---

## 1.10 Cardinality Mappings

Understanding the 1:1 and 1:many relationships is critical for writing correct queries.

```
┌─────────────────────────────────────────────────────────────────┐
│                    CARDINALITY RELATIONSHIPS                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   CONVERSATION ──────┬────▶ TURN 1 (messageId)    [1:MANY]     │
│   (conversationId)   ├────▶ TURN 2 (messageId)                 │
│                      └────▶ TURN 3 (messageId)                 │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   TURN ──────────────────────▶ User message       [1:1]        │
│   (messageId)                  (exactly one)                    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   TURN ──────────────┬────▶ LLM call 1            [1:MANY]     │
│   (messageId)        │      (tool-use or final)                 │
│                      ├────▶ LLM call 2                          │
│                      │      (tool-use or final)                 │
│                      └────▶ LLM call N                          │
│                             (always final response)             │
│                                                                 │
│   Formula: numRequests = sum(toolCounts) + 1                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Summary Table

| From | To | Cardinality | Notes |
|------|-----|-------------|-------|
| `conversationId` | Turn (`messageId`) | **1:many** | One conversation has many turns |
| `messageId` | `turnIndex` | **1:1** | Same turn, different identifiers |
| Turn | User message | **1:1** | Exactly one user message per turn |
| Turn | LLM call (`llmCalls[]`) | **1:many** | N calls per turn (tool-use + final) |
| LLM call | Tool call | **0:1** | An LLM call may or may not call a tool |

---

## 1.11 Token Accumulation Across Turns

As a conversation progresses, `promptTokens` grows because **all previous context is included**:

```
Turn 1 (with tools):
  llmCalls[0].promptTokens = 11,317   (initial context)
  llmCalls[3].promptTokens = 21,934   (after 3 tool results)
  
Turn 2 (text only):
  llmCalls[0].promptTokens = 24,426   (Turn 1 context + Turn 2 user message)
  
Turn 3 (text only):
  llmCalls[0].promptTokens = 24,989   (Turn 1-2 context + Turn 3 user message)
```

**Notice:** Each turn's first LLM call includes ALL previous conversation history!

---

## Next: [02_ROUTING_STRATEGIES.md](02_ROUTING_STRATEGIES.md)

Continue to learn about session-based vs conversation-aware routing approaches.

