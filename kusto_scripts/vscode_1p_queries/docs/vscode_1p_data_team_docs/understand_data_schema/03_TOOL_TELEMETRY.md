# Understanding Copilot Agent Mode Tool Telemetry

This document explains how tool usage is tracked in GitHub Copilot (VS Code) agent mode telemetry.

**Related Documents:**
- [Data Schema](./01_DATA_SCHEMA.md) — Conversation structure and data composition
- [Token Telemetry](./02_TOKEN_TELEMETRY.md) — Token tracking and measurement

---

## 1. Tool Data Overview

Copilot agent mode telemetry captures two types of tool information:

| Type | Description | Example |
|------|-------------|---------|
| **Tool Definitions** | Tools available to the model (sent in system message) | `["read_file", "write_file", "grep_search", ...]` |
| **Tool Invocations** | Tools actually called during a turn with frequency | `{"read_file": 2, "write_file": 1}` |

---

## 2. Data Source: `toolCallDetailsInternal`

Both tool definitions and invocations come from a **single telemetry event**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Event: GitHub.copilot-chat/toolCallDetailsInternal                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  When Captured: AFTER turn completes                                        │
│  Granularity: Per TURN (not per LLM call)                                  │
│  Join Key: messageId                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  Key Fields:                                                                │
│    • availableTools      - JSON array of tool names available              │
│    • availableToolCount  - Number of tools available                       │
│    • toolCounts          - JSON object with invocation frequency           │
│    • turnEndReason       - How the turn ended (success, failed, etc.)      │
│    • numRequests         - Number of LLM calls in the turn                 │
│    • turnDuration        - Total turn duration in milliseconds             │
│    • responseType        - "success" or error type                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Important: NOT from `engine.messages.length`

Tool data comes from `toolCallDetailsInternal`, NOT from the token events:

| Event | Data Type | Granularity |
|-------|-----------|-------------|
| `engine.messages.length` (INPUT) | Token estimates | Per LLM call |
| `engine.messages.length` (OUTPUT) | Actual tokens | Per LLM call |
| `toolCallDetailsInternal` | Tool metadata | **Per turn** |

---

## 3. Tool Definitions

### What Are Tool Definitions?

Tool definitions are the JSON schemas of all tools available to the model. They are:
- Sent in the **system message** every LLM call
- Part of `systemTokens` (Copilot's estimate)
- Billed as part of `promptTokens` (LLM's actual tokens)

### Example `availableTools` Field

```json
[
  "create_directory",
  "create_file", 
  "read_file",
  "replace_string_in_file",
  "grep_search",
  "run_in_terminal",
  "get_errors",
  ...
]
```

### Token Impact

Tool definitions contribute significant token overhead:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BASELINE TOKEN OVERHEAD (before any tool is invoked)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Component                    │ Typical Token Count                        │
│  ─────────────────────────────┼────────────────────────────────────────────│
│  System Prompt                │ ~3,000 tokens                              │
│  Tool Definitions (78 tools)  │ ~8,000-15,000 tokens                       │
│  User Message                 │ ~100-5,000 tokens                          │
│  ─────────────────────────────┼────────────────────────────────────────────│
│  TOTAL BASELINE               │ ~12,000-23,000 tokens                      │
│                                                                             │
│  NOTE: Tool definitions are sent with EVERY LLM call, even if no tools     │
│        are invoked. This is the "cost of having tools available."          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tool Count Varies

The number of available tools can vary:
- **Within a turn**: CONSTANT (same tools available for all LLM calls)
- **Across turns**: CAN CHANGE (user may enable/disable MCP tools)

```
Turn 1: availableToolCount = 78
Turn 2: availableToolCount = 78  ← Same
Turn 3: availableToolCount = 84  ← User enabled MCP tools
Turn 4: availableToolCount = 84  ← Same
```

---

## 4. Tool Invocations

### What Are Tool Invocations?

Tool invocations are the tools the model actually called during a turn, with their call frequency.

### Example `toolCounts` Field

```json
{
  "read_file": 7,
  "run_in_terminal": 2,
  "create_file": 5,
  "file_search": 1,
  "replace_string_in_file": 4
}
```

### Token Impact

When a tool is invoked:
1. The model decides to call a tool (generates tool call in `completionTokens`)
2. The tool executes and returns a result
3. The result is added to context for the next LLM call
4. Result tokens are counted in `toolResultTokens` (estimate) and `promptTokens` (actual)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TOOL INVOCATION TOKEN FLOW                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  LLM Call 1: promptTokens = 20,000                                         │
│      ↓ Model generates: "I'll read the file..."                            │
│      ↓ Tool call: read_file("config.json")                                 │
│                                                                             │
│  Tool executes → Returns 5,000 characters of content                       │
│      ↓                                                                      │
│  Copilot estimates: toolResultTokens += 1,234                              │
│                                                                             │
│  LLM Call 2: promptTokens = 21,500                                         │
│      ↑ Previous context + tool result                                      │
│      ↓ Model generates: "I'll also check the tests..."                     │
│      ↓ Tool call: read_file("test.js")                                     │
│                                                                             │
│  Tool executes → Returns 3,000 characters                                  │
│      ↓                                                                      │
│  Copilot estimates: toolResultTokens += 800                                │
│                                                                             │
│  LLM Call 3: promptTokens = 22,800                                         │
│      ↑ Previous context + both tool results                                │
│      ↓ Model generates final response (no tool call)                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Relationship to Token Fields

### ⚠️ CRITICAL: Actual vs Estimate Are PARALLEL Measurements

**Common Misconception**: "Actual is calculated FROM estimates" — **THIS IS WRONG!**

ACTUAL and ESTIMATE are **TWO INDEPENDENT MEASUREMENTS** of the **SAME CONTENT**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  THE SAME CONTENT (system prompt + tool defs + user msg + tool results)     │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  ┌─────────────────────────────┐    ┌─────────────────────────────┐        │
│  │  COPILOT'S TOKENIZER        │    │  LLM's TOKENIZER            │        │
│  │  (fast, client-side)        │    │  (actual, server-side)      │        │
│  │  ─────────────────────────  │    │  ─────────────────────────  │        │
│  │  When: BEFORE sending       │    │  When: AFTER processing     │        │
│  │  Purpose: Context mgmt      │    │  Purpose: BILLING           │        │
│  ├─────────────────────────────┤    ├─────────────────────────────┤        │
│  │  systemTokens = 13,551      │    │                             │        │
│  │  userTokens = 22,894        │    │  promptTokens = 46,648      │        │
│  │  assistantTokens = 1,034    │    │  (single combined number)   │        │
│  │  toolResultTokens = 38,484  │    │                             │        │
│  │  ─────────────────────────  │    │                             │        │
│  │  trajectoryTotal = 75,963   │    │                             │        │
│  └─────────────────────────────┘    └─────────────────────────────┘        │
│                                                                             │
│  SAME CONTENT → DIFFERENT TOKENIZERS → DIFFERENT NUMBERS!                  │
│  (75,963 vs 46,648 = 38% difference due to tokenizer mismatch)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why We Have Both

| Measurement | Tokenizer | When Measured | Purpose | Breakdown? |
|-------------|-----------|---------------|---------|------------|
| **Estimates (Copilot)** | Fast client-side | BEFORE sending | Decide truncation | ✅ By role |
| **Actual (LLM API)** | Model's tokenizer | AFTER processing | Billing | ❌ Combined |

### The Key Insight

- **Estimates give us BREAKDOWN** (system, user, assistant, tool - separately)
- **Actual gives us TOTAL** (everything combined, no breakdown available)
- **Different tokenizers** = numbers WON'T match (10-40% difference is normal)
- **Neither is "based on" the other** — they are parallel measurements

### How Tools Affect Token Estimates (Copilot)

| Token Field | Tool Contribution |
|-------------|-------------------|
| `systemTokens` | Includes tool DEFINITIONS (JSON schemas) |
| `toolResultTokens` | Includes tool RESULTS (after invocation) |
| `trajectoryTotal` | Sum includes both definitions and results |

### How Tools Affect Actual Tokens (LLM API)

| Token Field | Tool Contribution |
|-------------|-------------------|
| `promptTokens` | Includes EVERYTHING (system with definitions + tool results + user + assistant) |
| `completionTokens` | Includes tool CALL generation (e.g., `{"tool": "read_file", "args": {...}}`) |

### Visual: What's INSIDE promptTokens

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  promptTokens (ACTUAL - billed by LLM) = 46,648                             │
│  ═══════════════════════════════════════════════                            │
│                                                                             │
│  Content (tokenized by LLM's tokenizer):                                    │
│  ┌─────────────────────────────────────┐                                   │
│  │ System message                      │                                   │
│  │   • System prompt text              │  Copilot estimates these          │
│  │   • Tool JSON schemas (definitions) │  separately: systemTokens         │
│  └─────────────────────────────────────┘                                   │
│  ┌─────────────────────────────────────┐                                   │
│  │ User messages                       │  → userTokens (estimate)          │
│  └─────────────────────────────────────┘                                   │
│  ┌─────────────────────────────────────┐                                   │
│  │ Assistant messages (history)        │  → assistantTokens (estimate)     │
│  └─────────────────────────────────────┘                                   │
│  ┌─────────────────────────────────────┐                                   │
│  │ Tool results                        │  → toolResultTokens (estimate)    │
│  │   • Output from read_file           │                                   │
│  │   • Output from grep_search         │                                   │
│  │   • etc.                            │                                   │
│  └─────────────────────────────────────┘                                   │
│                                                                             │
│  LLM counts ALL of this together = 46,648 promptTokens                     │
│  Copilot counts each part separately = 75,963 total (different tokenizer!) │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Turn End Reasons

The `turnEndReason` field indicates how a turn completed:

| Value | Frequency | Meaning | Data Quality |
|-------|-----------|---------|--------------|
| `stopped` | 63.2% | Normal completion | ✅ Good |
| `toolUse` | 28.0% | Tool was used, turn continues | ✅ Good |
| `cancelled` | 5.2% | User cancelled | ❌ Exclude |
| `maxToolCalls` | 3.1% | Hit tool invocation limit | ⚠️ May be incomplete |
| `failed` | 0.4% | LLM call failed | ❌ Exclude |
| `networkError` | 0.2% | Network error | ❌ Exclude |

### Quality Filtering

For SFT data, exclude conversations with:
- `failed` turns
- `cancelled` turns
- `networkError` turns

---

## 7. Granularity: Turn Level vs LLM Call Level

### Current Limitation

Tool data is captured at **turn level**, not per LLM call:

| Data | Granularity | Can Associate with LLM Calls? |
|------|-------------|-------------------------------|
| Token data | Per LLM call | ✅ Yes |
| Tool definitions | Per turn | ❌ No (but same for all calls in turn) |
| Tool invocations | Per turn | ❌ No (aggregated count only) |

### What This Means

We know:
- ✅ Turn 1 had 5 LLM calls
- ✅ Turn 1 invoked `{"read_file": 2, "write_file": 1}`
- ✅ `toolResultTokens` grew between LLM calls

We DON'T know:
- ❌ Which specific LLM call invoked which tool
- ❌ Exact order of tool invocations

### Inferring Tool Usage from Token Growth

You can infer tool invocations by observing `toolResultTokens` growth:

```
Turn 1 llmCalls:
  Call 1: toolResultTokens = 0        ← No tools invoked yet
  Call 2: toolResultTokens = 5,000    ← Tool was invoked between call 1-2
  Call 3: toolResultTokens = 5,000    ← No new tool invocation
  Call 4: toolResultTokens = 8,500    ← Another tool invoked between call 3-4
  Call 5: toolResultTokens = 8,500    ← No new tool invocation (final response)
```

---

## 8. Output Schema in SFT Data

The `tools` object in the output:

```json
{
  "turnIndex": 1,
  "messageId": "...",
  "userMessage": "...",
  "modelMessage": "...",
  "llmCalls": [...],
  "turnSummary": {...},
  
  "tools": {
    "definitions": {
      "names": ["create_file", "read_file", "grep_search", ...],
      "count": 78
    },
    "invocations": {
      "withFrequency": {"read_file": 2, "replace_string_in_file": 1}
    }
  },
  
  "numRequests": 5,
  "turnDurationMs": 27188
}
```

---

## 9. Exploration Queries

### List Available Tools
```kql
AppEvents
| where TimeGenerated > ago(1d)
| where Name == "GitHub.copilot-chat/toolCallDetailsInternal"
| extend availableTools = tostring(Properties["availableTools"])
| where isnotempty(availableTools)
| project availableTools
| take 5
```

### Top Invoked Tools
```kql
AppEvents
| where TimeGenerated > ago(1d)
| where Name == "GitHub.copilot-chat/toolCallDetailsInternal"
| extend toolCounts = tostring(Properties["toolCounts"])
| where isnotempty(toolCounts) and toolCounts != "{}"
| project toolCounts
| take 20
```

### Tool Events Summary
```kql
AppEvents
| where TimeGenerated > ago(1d)
| where Name contains "tool" or Name contains "virtual"
| summarize count() by Name
| order by count_ desc
```

### Turn End Reason Distribution
```kql
AppEvents
| where TimeGenerated > ago(1d)
| where Name == "GitHub.copilot-chat/toolCallDetailsInternal"
| extend turnEndReason = tostring(Properties["turnEndReason"])
| summarize count() by turnEndReason
| order by count_ desc
```

---

## 10. Related Documents

| Document | Description |
|----------|-------------|
| [01_DATA_SCHEMA.md](./01_DATA_SCHEMA.md) | Conversation structure, hierarchy, completeness |
| [02_TOKEN_TELEMETRY.md](./02_TOKEN_TELEMETRY.md) | Token tracking, trajectory, truncation |

---

## 11. Key Takeaways

1. **Tool definitions** are sent in every system message, contributing ~8-15K tokens overhead
2. **Tool invocations** are captured at turn level (aggregated, not per LLM call)
3. **Both come from `toolCallDetailsInternal`** event, NOT from token events
4. **Use `turnEndReason`** to filter out failed/cancelled turns for quality data
5. **Tool definitions can change** between turns if user enables/disables MCP tools
6. **Tool results grow `toolResultTokens`** as tools are invoked during a turn

