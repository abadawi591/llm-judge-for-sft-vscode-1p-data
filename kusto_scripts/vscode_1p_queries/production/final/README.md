# Final Production Queries

These production queries incorporate all learnings from the token mechanics exploration documented in `../docs/vscode_1p_data_team_docs/understand_data_schema/README.md`.

---

## Query Selection Guide

| Query | When to Use | Memory Usage | Output Size |
|-------|-------------|--------------|-------------|
| `sft_simple_final.kql` | Quick extraction, don't need token breakdown | **Low** | ~500 conversations |
| `sft_stratified_final.kql` | Balanced sampling across turn lengths with full breakdown | **Medium** | ~13K conversations |
| `sft_with_trajectory_final.kql` | Detailed per-call analysis, truncation detection | **High** | ~50 conversations |

---

## Key Improvements Over Previous Versions

### 1. Correct Truncation Detection

**Before (WRONG):**
```kusto
// Don't do this - measures tokenizer difference, not truncation!
isTruncated = truncationDelta > 1000
```

**After (CORRECT):**
```kusto
// This is the only reliable truncation indicator
exceededWindow = trajectoryTotal > maxTokenWindow
```

### 2. Full Token Breakdown

Each LLM call now includes:
- **From LLM API (ACTUAL):** `promptTokens`, `completionTokens`, `maxTokenWindow`
- **From Copilot (ESTIMATES):** `systemTokens`, `userTokens`, `assistantTokens`, `toolResultTokens`
- **Analysis:** `exceededWindow`, `tokenizerRatio`, `hasTrajectory`

### 3. Correct Joining Strategy

Uses `callIndex` (via `row_number()`) to correctly join INPUT and OUTPUT events:

```kusto
// Add callIndex within each messageId (1, 2, 3, ...)
let tokenEvents = 
    tokenEventsRaw
    | extend callIndex = row_number(1, messageId != prev(messageId));
```

This avoids the timestamp mismatch issues that caused incorrect joins in earlier versions.

---

## Output Schema

All queries output conversations with this structure:

```json
{
  "conversationId": "abc-123",
  "userName": "user@example.com",
  "capturedTurnCount": 5,
  "isComplete": true,
  "turns": [
    {
      "turnIndex": 1,
      "messageId": "msg-001",
      "userMessage": "Please read my config...",
      "modelMessage": "I'll read the file...",
      "llmCalls": [
        {
          "callIndex": 1,
          // From LLM API (ACTUAL - for cost):
          "promptTokens": 24958,
          "completionTokens": 172,
          "model": "claude-opus-4.5",
          "maxTokenWindow": 127997,
          // From Copilot (ESTIMATES - for analysis):
          "trajectory": {
            "systemTokens": 14722,      // CONSTANT within turn
            "userTokens": 3916,         // CONSTANT within turn
            "assistantTokens": 0,       // GROWS within turn
            "toolResultTokens": 0,      // GROWS within turn
            "total": 18638
          },
          // Analysis:
          "hasTrajectory": true,
          "exceededWindow": false,      // TRUE = truncation!
          "tokenizerRatio": 1.34
        }
      ],
      "turnSummary": {
        "maxPromptTokens": 78559,
        "maxTrajectoryTotal": 201547,
        "maxTokenWindow": 127997,
        "hasTruncation": true,
        "llmCallCount": 9
      },
      "toolCounts": "{\"read_file\":5,\"run_terminal\":2}",
      "numRequests": 7,
      "turnDurationMs": 45000
    }
  ]
}
```

---

## Field Semantics

### Turn-Level Summary

| Field | Description |
|-------|-------------|
| `maxPromptTokens` | Maximum `promptTokens` across all LLM calls in the turn |
| `maxTrajectoryTotal` | Maximum `trajectoryTotal` across all LLM calls |
| `maxTokenWindow` | Model's context window limit |
| `hasTruncation` | TRUE if ANY call had `exceededWindow = true` |
| `llmCallCount` | Number of LLM calls in this turn |

### Per-Call Fields

| Field | Source | Behavior in Turn | Description |
|-------|--------|------------------|-------------|
| `promptTokens` | LLM API | Grows | Actual tokens charged |
| `completionTokens` | LLM API | Varies | Model's response tokens |
| `systemTokens` | Copilot | **Constant** | System prompt + tool definitions |
| `userTokens` | Copilot | **Constant** | User's message |
| `assistantTokens` | Copilot | **Grows** | Model's prior responses |
| `toolResultTokens` | Copilot | **Grows** | Tool outputs accumulated |
| `exceededWindow` | Calculated | - | TRUE = truncation occurred |
| `tokenizerRatio` | Calculated | - | `promptTokens / trajectoryTotal` |

---

## Memory Optimization

If you encounter `E_LOW_MEMORY_CONDITION` errors:

1. **Reduce time window**: `let timeStart = ago(6h);` instead of `ago(7d)`
2. **Filter early**: Add `| where ...` filters before expensive operations
3. **Skip huge trajectories**: `| where strlen(messagesJson) < 500000`
4. **Use `sft_simple_final.kql`**: Skips trajectory parsing entirely

---

## Completeness Check

All queries enforce conversation completeness:

```kusto
| where minTurnIndex == 1           // Starts at turn 1
| where capturedTurnCount == maxTurnIndex  // No missing turns
```

This ensures only complete conversations (no telemetry gaps) are included.
