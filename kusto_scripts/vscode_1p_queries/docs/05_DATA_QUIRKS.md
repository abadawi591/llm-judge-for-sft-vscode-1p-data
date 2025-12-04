# Part 5: Data Quirks and Solutions

This document covers known issues in the telemetry data and how the queries handle them.

---

## 5.1 Message Duplication (CRITICAL)

### Problem

Every time the model takes a new action (e.g., calling a tool), the messages are re-sent to telemetry, causing duplication.

### Solution

Deduplicate in two steps:

```kql
// Step 1: Dedupe by messageId + source (keep longest text)
let dedupedByMessageId = 
    rawMessages
    | summarize arg_max(strlen(messageText), *) by conversationId, messageId, source;

// Step 2: Dedupe model messages by text (keep first occurrence)
let dedupedModel = 
    dedupedByMessageId
    | where source == "model"
    | summarize arg_min(TimeGenerated, *) by conversationId, source, messageText;
```

---

## 5.2 No Mode/ConversationId in Token Events

### Problem

`engine.messages.length` events don't have `mode` or `conversationId` fields.

### Solution

Join with message events via `headerRequestId` = `messageId`:

```kql
tokenEvents
| join kind=inner messageEvents on $left.headerRequestId == $right.messageId
```

---

## 5.3 Multiple Token Events Per Turn

### Problem

A single turn can have multiple token events (one per LLM call when tools are used).

### Why This Happens

```
Turn with 2 tool calls (messageId: abc-123):
  LLM call 1: promptTokens=5000  → Token event 1
  LLM call 2: promptTokens=6000  → Token event 2  
  LLM call 3: promptTokens=7000  → Token event 3 (final)
```

Querying for `messageId = abc-123` returns **3 rows**, not 1.

### Solution

Keep each LLM call as a separate entry in an `llmCalls` array:

```kql
| summarize 
    llmCalls = make_list(pack(
        "promptTokens", promptTokens,
        "completionTokens", completionTokens,
        "model", model
    ))
    by messageId
```

---

## 5.4 make_list Does NOT Preserve Order

### Problem

Kusto's `make_list()` doesn't guarantee order even with `order by` before it.

### Solution

Use `mv-apply` to sort after aggregation:

```kql
| mv-apply items on (
    order by toint(items.turnIndex) asc
    | summarize items = make_list(items)
)
```

---

## 5.5 Reserved Keywords

### Problem

`time` is a reserved keyword in Kusto.

### Solution

Use `timestamp` or `TimeGenerated` instead.

---

## 5.6 Token Data May Be Missing

### Problem

Not all messages have corresponding token events.

### Solution

Add filter or use `leftouter` join:

```kql
| where isnotnull(totalPromptTokens)
// OR
| join kind=leftouter tokenEvents on messageId
```

---

## 5.7 Partial Conversation Captures

### Problem

Due to time-window queries, we often capture only part of a conversation.

### Impact

- `minTurnIndex > 1` means we missed early turns
- First captured turn's `promptTokenDelta` is inflated

### Solution

Filter for complete conversations:

```kql
| where minTurnIndex == 1
| where capturedTurnCount == maxTurnIndex
```

---

## 5.8 Response Type Filtering

### Problem

~7% of turns have non-success response types (cancelled, failed, etc.)

### Distribution (Verified 2025-12-03)

| responseType | Count | Percentage |
|--------------|-------|------------|
| **success** | 294,411 | 92.8% |
| cancelled | 12,346 | 3.9% |
| maxToolCalls | 6,679 | 2.1% |
| failed | 2,351 | 0.7% |
| Other | 2,008 | 0.6% |

### Solution

Filter for success only in production queries:

```kql
| where responseType == "success"
```

This may cause gaps in `turnIndex` sequences.

---

## 5.9 ID Field Naming Inconsistency

### Problem

The same ID has different names across events:

| Canonical Name | Also Known As |
|----------------|---------------|
| `messageId` | `headerRequestId`, `requestId` |
| `conversationId` | `conversation_id` |

### Solution

Always use explicit field extraction:

```kql
| extend messageId = tostring(Properties["messageId"])
| extend messageId = tostring(Properties["headerRequestId"])  // In token events
```

---

## 5.10 Context Window Resets

### Problem

Sometimes `promptTokens` drops suddenly (context was reset/truncated).

### How It Appears

```
Call 3: promptTokens = 131,032  →  promptTokenDelta = 8,538
Call 4: promptTokens = 21,271   →  promptTokenDelta = -109,761  ← RESET!
```

### Why This Happens

| Cause | Description |
|-------|-------------|
| Context window limit | Model reached max tokens, old context dropped |
| Conversation compaction | System summarized/removed old messages |
| Sub-task isolation | Agent started fresh context |

### This is Valuable Data!

Negative `promptTokenDelta` tells you when context was lost, which affects model coherence.

---

## Back to: [AGENT_SFT_DATA_GUIDE.md](../AGENT_SFT_DATA_GUIDE.md)

Return to the main guide.

