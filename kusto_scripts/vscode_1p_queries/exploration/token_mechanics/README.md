# Token Mechanics Investigation

This folder contains queries to understand how tokens are tracked in agent mode telemetry.

## 🎯 KEY FINDING: Two Different `messagesJson` Formats!

**Critical Discovery** from official Copilot data team documentation:

The `messagesJson` field exists in TWO events with DIFFERENT formats:

| Event | `messagesJson` Contains | Purpose |
|-------|------------------------|---------|
| `engine.messages` | **Actual text content** (system prompt, user input, assistant response) | Full conversation trajectory |
| `engine.messages.length` | **Length metrics** (token/character estimates) | Message length statistics |

From `CONVERSATION_XML_TAGS_20251001.md`:
> "Source events: exact event `GitHub.copilot.chat/engine.messages` **(we only parse `messagesJson`, never `engine.messages.length`)**"

This explains why `trajectoryTotal` (sum of `content` from `engine.messages.length`) differs from `promptTokens`:
- **`content` field** = Copilot's **pre-computed estimate** (before API call)
- **`promptTokens`** = LLM API's **actual charged tokens** (after API call)

## 📊 Token Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CONTEXT PROCESSING PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STAGE 1: engine.messages.length (INPUT)                                    │
│           messagesJson.content = ESTIMATED token counts per role            │
│           trajectoryTotal = sum of all content values                       │
│                                                                             │
│              ↓ MESSAGE SELECTION (based on maxTokenWindow)                  │
│                                                                             │
│  STAGE 2: model.modelCall.input                                             │
│           messageUuids = WHICH messages actually sent (subset)              │
│           messageCount = how many messages fit in window                    │
│                                                                             │
│              ↓ API TOKENIZES & PROCESSES                                    │
│                                                                             │
│  STAGE 3: model.modelCall.output                                            │
│           promptTokens = ACTUAL tokens charged by LLM API                   │
│           (Different tokenizer = different count!)                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

The gap is due to BOTH:
1. Message selection (older messages dropped to fit context window)
2. Tokenizer differences (estimate vs actual API tokenization)
```

## Key Questions (Answered ✅)

| Question | Answer | Evidence |
|----------|--------|----------|
| Does `promptTokens` include tool tokens? | ✅ Yes | Query 14 |
| Why is `promptTokens` << `trajectoryTotal`? | ✅ Tokenizer mismatch + selection | Queries 32, 34 |
| Is it due to caching? | ❌ No (only 2.3% correlation) | Query 30 |
| What is `messagesJson.content`? | Token **estimate** (not actual) | Query 34, Official docs |
| Are all messages sent? | ✅ Yes (100% selection ratio) | Query 33 |

## Additional Key Insights from Official Docs

From `CONVERSATION_TRAJECTORY_EXTRACTION.md`:

1. **Snapshot, NOT Cumulative**: "Each `engine.messages` entry is a **discrete LLM API call snapshot**, not a cumulative transcript."

2. **messagesJson can be split**: Large conversations use `messagesJson_02`, `messagesJson_03`, etc. (up to 100 parts)

3. **Model fields mutually exclusive**: `baseModel` and `request.option.model` never co-occur

4. **turnIndex = user message count**: "turnIndex is the Nth user message (0‑based), not index in entire message array"

## Query Files

### Foundation Queries (01-10)
| File | Purpose |
|------|---------|
| `01_aggregate_by_tool_usage.kql` | Compare turns WITH vs WITHOUT tools |
| `02_turns_without_tools.kql` | Detailed view of turns without tools |
| `03_turns_with_tools.kql` | Detailed view of turns with tools |
| `04_verify_tool_token_sum.kql` | Verify tool token calculation |
| `05_schema_output_direction.kql` | Schema: engine.messages.length (output) |
| `06_schema_input_direction.kql` | Schema: engine.messages.length (input) |
| `07_schema_tool_call_details.kql` | Schema: toolCallDetailsInternal |
| `08_search_tool_token_fields.kql` | Search for tool+token fields |
| `09_list_all_measurements.kql` | List all measurement fields |
| `10_token_progression_detailed.kql` | Side-by-side token comparison |

### Anomaly Investigation (11-13)
| File | Purpose |
|------|---------|
| `11_anomaly_no_tools_multiple_calls.kql` | Why no-tool turns have multiple LLM calls |
| `12_anomaly_tools_but_one_request.kql` | Why tool turns have only 1 request |
| `13_prompt_growth_without_tools_breakdown.kql` | Prompt growth breakdown |

### Token Mechanics Deep Dive (14-24)
| File | Purpose |
|------|---------|
| `14_prove_prompt_includes_tools.kql` | Verify promptTokens includes tool tokens |
| `15_multi_turn_token_trace.kql` | Trace tokens across turns |
| `16-19` | System prompt and completion verification |
| `20-24` | Trajectory and message event exploration |

### Gap Investigation (25-33) ⭐ KEY QUERIES
| File | Purpose |
|------|---------|
| `25_deep_dive_single_conversation.kql` | Find complete conversation for analysis |
| `26_conversation_turn_details.kql` | Token details per turn |
| `27_single_message_trajectory.kql` | Parse trajectory per LLM call |
| `28_compare_prompt_vs_trajectory.kql` | Compare promptTokens vs trajectoryTotal |
| `29_investigate_caching.kql` | Investigate copilot_cache_control |
| `30_verify_caching_telemetry.kql` | ❌ Disproved caching hypothesis |
| `31_investigate_content_field.kql` | Verify content = token count |
| `32_verify_context_truncation.kql` | ✅ Confirmed context truncation |
| `33_verify_message_selection.kql` | Verify via model.modelCall.input |

## Run Order

1. Start with `32_verify_context_truncation.kql` - shows the ~30% ratio
2. Run `30_verify_caching_telemetry.kql` - disproves caching hypothesis
3. Run `33_verify_message_selection.kql` - shows message selection mechanism

## Schema Reference

See `../copilot_chat_events_schema.txt` for full event documentation.

## 📚 Official Documentation (Copilot Data Team)

These official documents from the VS Code Copilot data team provide authoritative information:

| Document | Location | Key Topics |
|----------|----------|------------|
| **CONVERSATION_TRAJECTORY_EXTRACTION.md** | `../docs/vscode_1p_data_team_docs/` | How trajectories are extracted; snapshot vs cumulative; deduplication |
| **CONVERSATION_XML_TAGS_20251001.md** | `../docs/vscode_1p_data_team_docs/` | XML tags in user messages; confirms engine.messages vs engine.messages.length difference |
| **TELEMETRY_SCHEMA_20251001.md** | `../docs/vscode_1p_data_team_docs/` | Full schema of all telemetry events (29 event types) |

### Key Quotes from Official Docs

> "Source events: exact event `GitHub.copilot.chat/engine.messages` **(we only parse `messagesJson`, never `engine.messages.length`)**"
> — *CONVERSATION_XML_TAGS_20251001.md*

> "Each `engine.messages` entry is a **discrete LLM API call snapshot**, not a cumulative transcript."
> — *CONVERSATION_TRAJECTORY_EXTRACTION.md*

> "`turnIndex` is the Nth user message (0‑based), not index in entire message array."
> — *CONVERSATION_TRAJECTORY_EXTRACTION.md*

