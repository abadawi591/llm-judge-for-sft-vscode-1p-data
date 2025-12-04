# Part 4: Query Reference

This document lists all available Kusto queries and their purposes.

---

## 4.1 Folder Structure

```
vscode_1p_queries/
├── AGENT_SFT_DATA_GUIDE.md              # Main entry point
├── docs/                                 # Documentation (this folder)
│   ├── 01_DATA_STRUCTURE.md
│   ├── 02_ROUTING_STRATEGIES.md
│   ├── 03_DATA_BALANCING.md
│   ├── 04_QUERY_REFERENCE.md
│   └── 05_DATA_QUIRKS.md
│
├── production/                           # ⭐ USE THESE FOR DATA EXTRACTION
│   ├── sft_nested_json.kql
│   ├── sft_nested_json_simple.kql
│   ├── sft_complete_conversations_3to10.kql
│   ├── sft_session_router_first_turns.kql
│   └── sft_stratified_by_turn_count.kql
│
├── exploration/                          # Investigation queries
│   ├── complete_3turn_conversations_with_delta.kql  # ⭐ Sample data generator
│   ├── discover_events.kql
│   ├── message_schema.kql
│   ├── token_schema.kql
│   ├── tool_schema.kql
│   ├── token_breakdown_by_tool_use.kql
│   ├── tool_tokens.kql
│   ├── exact_tool_tokens.kql
│   └── model_switching.kql
│
└── verification/                         # Verification queries
    ├── token_accumulation.kql
    ├── numRequests_formula.kql
    └── delta_accuracy.kql
```

---

## 4.2 Production Queries

### Which Query Should I Use?

| Your Goal | Query | Output |
|-----------|-------|--------|
| Session-based routing training | `sft_session_router_first_turns.kql` | First turns with complexity signals |
| Conversation-aware routing training | `sft_stratified_by_turn_count.kql` | Stratified conversations by length |
| Complete conversations with all metrics | `sft_complete_conversations_3to10.kql` | Complete convos, reliable deltas |
| Quick extraction, no delta | `sft_nested_json_simple.kql` | Nested JSON, fast |
| Full data including partials | `sft_nested_json.kql` | All conversations |

---

### sft_nested_json.kql

**Purpose:** Main SFT extraction query with full nested JSON output.

**Features:**
- Full nested JSON structure
- `promptTokenDelta` calculated (⚠️ unreliable for partial captures)
- All token metrics
- Tool usage details

**Output fields:**
```json
{
  "conversationId": "...",
  "userName": "...",
  "capturedTurnCount": 5,
  "minTurnIndex": 1702,
  "maxTurnIndex": 1706,
  "turns": [...]
}
```

---

### sft_nested_json_simple.kql

**Purpose:** Simplified version without `promptTokenDelta` calculation.

**Use when:**
- You don't need per-call token deltas
- You want faster query execution
- You'll calculate deltas in post-processing

---

### sft_complete_conversations_3to10.kql

**Purpose:** Extract only complete conversations with 3-10 turns.

**Features:**
- Completeness guarantee: `minTurnIndex == 1 AND capturedTurnCount == maxTurnIndex`
- `isComplete: true` flag
- `promptTokenDelta` is **reliable** (completeness ensures accurate first-turn delta)
- 24-hour time window (to capture full conversations)

**Filters:**
```kql
| where minTurnIndex == 1
| where capturedTurnCount == maxTurnIndex
| where capturedTurnCount >= 3
| where capturedTurnCount <= 10
```

---

### sft_session_router_first_turns.kql

**Purpose:** Extract first turns for session-based routing.

**Features:**
- First turns only (`turnIndex == 1`)
- Conversation metadata (total turns, duration)
- Pre-stratification signals: `isLikelyReasoning`, `complexityBucket`
- 7-day time window

**Output fields:**
```json
{
  "conversationId": "...",
  "userMessage": "...",
  "modelMessage": "...",
  "model": "claude-opus-4.5",
  "isLikelyReasoning": true,
  "complexityBucket": "moderate",
  "conversationTotalTurns": 10
}
```

---

### sft_stratified_by_turn_count.kql

**Purpose:** Stratified sampling by turn count buckets.

**Features:**
- Three buckets: A (3-5), B (6-10), C (11-20) turns
- Configurable sample sizes per bucket
- Complete conversations only
- `promptTokenDelta` included and reliable

**Default sample sizes:**
- Bucket A: 5,000 conversations
- Bucket B: 5,000 conversations
- Bucket C: 3,000 conversations

---

## 4.3 Exploration Queries

| Query | Purpose |
|-------|---------|
| `complete_3turn_conversations_with_delta.kql` | ⭐ Generate sample 3-turn complete convos with `promptTokenDelta` |
| `discover_events.kql` | Find all Copilot event types |
| `message_schema.kql` | Explore message event structure |
| `token_schema.kql` | Explore token event structure |
| `tool_schema.kql` | Explore tool call structure |
| `token_breakdown_by_tool_use.kql` | How tool use affects tokens |
| `tool_tokens.kql` | Initial tool token investigation |
| `exact_tool_tokens.kql` | Extract EXACT tool tokens from messagesJson |
| `model_switching.kql` | Users switching models mid-conversation |

---

## 4.4 Verification Queries

| Query | Finding |
|-------|---------|
| `token_accumulation.kql` | ✅ Confirms promptTokens grows over conversation |
| `numRequests_formula.kql` | ✅ Confirms `numRequests = sum(toolCounts) + 1` |
| `delta_accuracy.kql` | ⚠️ First delta is inaccurate for partial captures |

---

## 4.5 Event Types Reference

### Message Events: `GitHub.copilot-chat/conversation.messageText`

| Property | Type | Description |
|----------|------|-------------|
| `conversationId` | string | Conversation identifier |
| `messageId` | string | Turn identifier |
| `source` | string | `"user"` or `"model"` |
| `messageText` | string | The message content |
| `mode` | string | `"agent"` for agent mode |

### Token Events: `GitHub.copilot-chat/engine.messages.length`

| Property | Type | Description |
|----------|------|-------------|
| `headerRequestId` | string | = messageId |
| `message_direction` | string | `"input"` or `"output"` |
| `baseModel` | string | Model name |
| `promptTokens` | int | Tokens in prompt (output direction) |
| `completionTokens` | int | Tokens in completion (output direction) |

### Tool Events: `GitHub.copilot-chat/toolCallDetailsInternal`

| Property | Type | Description |
|----------|------|-------------|
| `messageId` | string | Turn identifier |
| `toolCounts` | string (JSON) | `{"read_file": 3, "list_dir": 2}` |
| `numRequests` | int | LLM API calls = sum(toolCounts) + 1 |
| `turnIndex` | int | Sequential turn number |
| `turnDuration` | int | Turn duration in ms |
| `responseType` | string | `"success"`, `"cancelled"`, etc. |

---

## Next: [05_DATA_QUIRKS.md](05_DATA_QUIRKS.md)

Continue to learn about data quirks and solutions.

