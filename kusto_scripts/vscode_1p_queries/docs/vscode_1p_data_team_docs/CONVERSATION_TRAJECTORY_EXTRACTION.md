# Conversation Trajectory Extraction

## What This Covers

- How the extractor rebuilds full conversations (system, user, assistant, tool) from raw telemetry
- Where key fields come from (mode, messagesJson, model) and how they are correlated
- The trajectory data model and enrichment (per-message mode, effective model)
- Known patterns and caveats (snapshots, system‑injected messages, tool calls)

Use this as the canonical guide to understand and use `extract`.

## Key Concepts

- Snapshot: Each `engine.messages` is a point‑in‑time snapshot of a conversation turn; snapshots can overlap and vary in completeness.
- Why duplicates exist: Multiple snapshots and multiple files/exports for the same conversation create “duplicates” with different completeness.
- Deduplication (de‑dup): Selecting one best trajectory per conversation and merging missing annotations from other snapshots when safe.
- ConversationId vs SessionId: `conversationId` identifies conversations in `engine.messages`; `sessionId` appears on interactiveSession* events and is used for correlation/enrichment.
- Tool metadata: Assistant `tool_calls` and tool `tool_call_id` link function calls to tool responses and are preserved/merged into the winner.

## Quick Start

- Directory (recommended):
  - `python cli.py extract cooked/08/17 -v`
- Single file:
  - `python cli.py extract telemetry.jsonl`
- Output format: JSONL (one conversation per line). Each line is a ConversationTrajectory object (see “Output Data Model”).

## Output Data Model

**Message**
- role: system | user | assistant | tool
- content: string (may be empty for assistant tool calls)
- mode: string | null (ask | agent | edit | custom) for user messages
 - model: string | null (response model for the last message; earlier messages may be filled from interactive session)
 - model_source: `engine` | `engine-request` | `interactiveSession`
 - model_conflict: boolean | null (true when interactive session disagrees with the engine’s last‑message model)
- tool_calls / tool_call_id: when assistant orchestrates tools

**ConversationTrajectory**
- conversation_id: conversationId
- messages: list[Message]
- context: extracted context (see “Context Fields”)
- metadata: { mode, intent, detectedIntent, timestamp, turnIndex, messageId }
- mode_distribution: counts by mode
- telemetry_type, file_path: provenance

## Sources of Truth and Field Mapping

- `GitHub.copilot.chat/engine.messages`
  - Conversation identifier: `conversationId` (used as the trajectory id)
  - Request identifier: `headerRequestId` (unique id for the engine request; used to correlate mode and session models)
  - Message payload: `messagesJson` (sometimes split as `messagesJson_02`, `messagesJson_03`, …)
  - Model fields: `baseModel` OR `request.option.model` (mutually exclusive in practice)
- `GitHub.copilot-chat/conversation.messageText`
  - Conversation identifier: `conversationId`
  - Mode and turn: `mode` and `turnIndex` (0‑based ordinal of user turns)
  - Source: `source` (we only record modes from `source == "user"`)
  - Optional request identifier: `headerRequestId` (when present, used for primary mode correlation)
- `GitHub.copilot.chat/inlineConversation.messageText` (secondary source)
  - Same shape as `conversation.messageText` for the fields we use: `conversationId`, `mode`, `turnIndex`, `source`, `headerRequestId`, `messageText`
  - Represents inline chat UI; we collect modes from here as well when `source == "user"`
- `GitHub.copilot-chat/interactiveSessionMessage`
  - Session identifier: `sessionId` (conceptually the same conversation as `engine.messages.conversationId`)
  - Request identifier: `requestId` (correlates to `engine.messages.headerRequestId`)
  - Model fields: `baseModel` or `model` (sometimes present; values like `auto` are ignored)
- `GitHub.copilot-chat/interactiveSessionResponse`
  - Same identifiers as above: `sessionId`, `requestId`
  - Model fields: `baseModel` or `model` (preferred over `interactiveSessionMessage` when both exist)

### Output Field Origins (Quick Map)

- ConversationTrajectory
  - `conversation_id`: engine.messages.conversationId
  - `messages[]`: parsed from engine.messages.messagesJson (correlation-aware path)
  - `metadata.timestamp/turnIndex/messageId`: engine.messages properties
  - `metadata.mode`: derived from per-message modes (first encountered user mode)
  - `mode_distribution`: counts of per-message modes
  - `telemetry_type`/`file_path`: provenance
  - `context{}`: properties (attachedContext, fileExcerpt, …) + message-body scan (message_contexts)

- Message
  - `role`/`content`: engine.messages.messagesJson
  - `mode`: conversation.messageText (via requestId or turnIndex correlation). Values: `ask`, `agent`, `edit`, `custom`.
  - `model`: engine last-message model (baseModel or request.option.model); earlier messages may be filled from interactiveSession*
  - `model_source`/`model_conflict`: enrichment when interactive session differs
  - `tool_calls` (assistant) / `tool_call_id` (tool): preserved from messagesJson; merged across snapshots when missing on the winner (role-aware)

Important: `engine.messages` snapshots do not include `mode`, and `conversation.messageText` doesn’t include the full conversation. We correlate them.

## Extraction Pipeline

Primary source and enrichment
- Primary transcript: `GitHub.copilot.chat/engine.messages` contains the per‑call conversation snapshot (system, user, assistant, tool).
- Missing attributes: per‑message mode and per‑message model are not fully present in these snapshots.
- Correlation sources:
  - Mode: `conversation.messageText` via `headerRequestId` (primary) or `turnIndex` (fallback, 0‑based user turns).
  - Non‑last message models: `interactiveSessionResponse`/`interactiveSessionMessage` via `(sessionId = conversationId, requestId = headerRequestId)`; ignore `auto`.
- Model policy: no trajectory‑level model; stamp only the last message from engine, fill earlier messages from interactive session when available.

Overview
- Phase 1: Collect conversation metadata and session models
- Phase 2: Extract from `engine.messages` and enrich (mode + model)
- Phase 3: Dedupe and merge per‑message annotations (and tool metadata)
- Phase 4: Context scan (properties + message body)
- Phase 5: Output and determinism

Phase 1 — Collect (per file)
- `conversation_modes[conversationId][turnIndex] = mode`
- `message_metadata[conversationId][turnIndex] = { source, messageId, timestamp, mode }`
- `request_modes[headerRequestId] = mode` (only when `source == "user"`)
- `session_models_by_request[sessionId][requestId] = { response: (ts, model) | None, message: (ts, model) | None }`
- Where implemented: `extraction/prompt_extractor.py::_extract_with_correlation` (streaming, first pass)

Phase 2 — Extract + Enrich (per `engine.messages` snapshot)
- Reconstruct `messagesJson` when split, then parse all roles.
- Tag per‑user `mode`:
  - Primary: `request_modes[headerRequestId]`
  - Fallback: `conversation_modes[conversationId][turnIndex]` aligned to user message order (0‑based turn count)
- Stamp `model` only on the last message of the snapshot (engine‑authoritative):
  - If last role is assistant → use `_extract_effective_model` (prefer `baseModel`; fallback to unwrapped `request.option.model`)
  - If last role is user/tool/system → use unwrapped `request.option.model`
- Fill earlier (non‑last) messages’ `model` from interactive session:
  - Lookup by `(sessionId = conversationId, requestId = headerRequestId)` in `session_models_by_request`
  - Prefer `response` over `message`; set `model_source = "interactiveSession"`
  - If session disagrees with engine on this request, set `model_conflict = true` on the last message (engine remains authoritative)
- Extract context (properties + structured signals from user message content)
- Compute `mode_distribution` and set `metadata.mode` as the first observed user mode
- Where implemented: `extraction/prompt_extractor.py::_extract_enhanced_trajectory`, `_extract_messages_with_mode`, `_extract_effective_model`

Phase 3 — Dedupe + Merge (global across files)
- Winner per `conversation_id`: highest message count; tie break by later `metadata.timestamp`.
- Merge missing per‑message annotations into the winner:
  - Always: `mode`, `model`, `model_source`, `model_conflict`
  - Role‑aware tool metadata (default ON): assistant `tool_calls` and tool `tool_call_id`
- Assistant messages with `tool_calls` are kept even when `content` is empty; skip only when both `content` is empty AND there are no `tool_calls`.
- Where implemented: in‑memory `_deduplicate_trajectories` and SQLite‑backed path in `extraction/prompt_extractor.py`.

Phase 4 — Context Scan
- Properties: `attachedContext`, `contextTypes`, `fileExcerpt`, `activeSelection`, `detectedParticipant`, `assignedIntent`.
- Message body (user messages): environment/workspace/editor/repo context, attachments, code snippets, file references, agent mentions; lists de-duplicated deterministically.
- Tag mapping is data-driven: the extractor and the conversation tag analyzer both load the shared catalog at `telemetry-processor/docs/schema/prompt_context_tags.json` (override via `PROMPT_CONTEXT_TAG_MAP` or `--context-tag-map`). Each entry defines the canonical tag name, optional legacy pattern, and context-routing metadata. The legacy hard-coded examples earlier in this doc are illustrative only—the catalog is the source of truth and may evolve.
- Unknown or newly observed tags are preserved under `message_contexts[].other_tags` with short snippets so they can be reviewed before promotion into the mapping.
- `cli.py extract` writes a per-run tag scan summary (`analysis/prompt_context/<timestamp>/tag_scan_summary.json` by default). Disable with `--no-context-tag-summary` or choose a custom directory with `--context-tag-summary-dir`. Feed this JSON to the LLM helper when preparing recommendation notes for docs or for extending the mapping. For a curated, human-readable inventory run `python cli.py conversation-tags …` to regenerate `docs/CONVERSATION_XML_TAGS_*.md`.
- Unknown or newly observed tags are preserved under `message_contexts[].other_tags` with short snippets so they can be reviewed before promotion into the mapping.
- `cli.py extract` writes a per-run tag scan summary (`analysis/prompt_context/<timestamp>/tag_scan_summary.json` by default). Disable with `--no-context-tag-summary` or choose a custom directory with `--context-tag-summary-dir`. Feed this JSON to the LLM helper when preparing recommendation notes for docs or for extending the mapping.
- CLI defers message‑body scan until after global dedupe for performance.
- Where implemented: `_extract_context` and deferred `_augment_context_from_messages_for_trajectory` in `extraction/prompt_extractor.py`.

Phase 5 — Output and Determinism
- Output: JSONL with one ConversationTrajectory per line.
- Ordering: files processed in sorted order; first‑seen conversation ordering preserved on the SQLite path.
- Sampling: deterministic with `--seed` and `--sample-mode`.
- Streaming: prefers streaming and falls back to non‑streaming only if no `engine.messages` were parsed during streaming.

Where Implemented (Quick Map)
- Collector and two‑pass driver: `extraction/prompt_extractor.py::_extract_with_correlation`
- Mode tagging: `extraction/prompt_extractor.py::_extract_messages_with_mode`
- Model stamping and conflicts: `extraction/prompt_extractor.py::_extract_enhanced_trajectory`, `_extract_effective_model`
- Dedupe + merge: `extraction/prompt_extractor.py::_deduplicate_trajectories` and SQLite path in `extract_from_directory`
- Context: `extraction/prompt_extractor.py::_extract_context`, `_augment_context_from_messages_for_trajectory`

#### Extractor Paths and Message Retention

- Primary path — Two‑pass, correlation‑aware (used by `cli.py extract`):
  - What it does: parses `engine.messages` snapshots, tags per‑user `mode` (via `headerRequestId` → `request_modes`, or `turnIndex` fallback), stamps last‑message `model`, fills earlier models from `interactiveSession*`, and flags `model_conflict` when session disagrees with engine.
  - Message retention: keeps assistant messages that carry `tool_calls` even when `content == ""`; only skips messages that have no `role` or have empty `content` and no `tool_calls`.
  - Implementation: `_extract_with_correlation` → `_extract_enhanced_trajectory` + `_extract_messages_with_mode` (see “Where Implemented”).
  - When it runs: always on the CLI path; prefers streaming and falls back to non‑streaming only if no `engine.messages` were parsed during streaming.

- Secondary path — Simple `messagesJson` helper (internal/legacy):
  - What it does: parses `messagesJson` and returns messages with `role` and non‑empty `content` only. Stamps only the last message’s model (no per‑message mode, no session model fill, no conflict flag).
  - Message retention: drops assistant messages that have `tool_calls` when their `content` is empty (tool metadata is lost on this path).
  - Implementation: `_extract_trajectory_from_messages_json` (invoked by `_extract_from_entry`).
  - When it runs: not used by the CLI’s main trajectory flow; only used if you call the extractor directly with `correlate_events=False`, or in certain legacy/tests/dev‑tool scenarios. Prefer the primary path for production outputs.

### Deduplication and Streaming

- Why duplicates exist: snapshots overlap across files/exports, and later snapshots may omit fields present in earlier ones. Deduplication selects a single winner per conversation.
- Deduplication selects a single “best” trajectory per `conversation_id` (highest message count; tie by latest timestamp)
- The CLI uses an on‑disk index to keep memory flat even on very large datasets; final output preserves first‑seen conversation ordering
- Streaming is preferred: the extractor streams both passes and falls back to the non‑streaming loader only if no `engine.messages` entries were parsed during streaming.

#### Merging Annotations Across Snapshots

When multiple snapshots exist for the same conversation, the dedupe reducer also merges missing per‑message annotations into the winner:

- Always merged: `mode`, `model`, `model_source`, `model_conflict` (only when the winner’s message is missing the field)
- Tool metadata (default ON): `tool_calls` (assistant) and `tool_call_id` (tool) are merged into the winner when they are present in another snapshot but missing in the winner
  - This preserves assistant function calls and tool responses even if later snapshots omit them
  - Advanced: can be disabled programmatically by constructing `PromptExtractor(merge_tool_metadata=False)`

### Context Extraction Performance

- Property‑level context is copied immediately from telemetry properties
- Message‑body context is extracted from user messages and saved under `context.message_contexts`
  - Examples: `environment_info`, `workspace_info`, `editor_context`, `repo_context`, `reminder_instructions`, `user_request`, `attachments`, `file_references`, `code_snippets`, `code_to_edit`, `agent_mentions`
- In the CLI, context scanning is deferred until after global deduplication so bodies are scanned once per kept trajectory (no change to which trajectory is selected)
- Order‑sensitive lists inside context (e.g., `file_references`) are de‑duplicated in a deterministic, first‑occurrence order

### Determinism

- Files are processed in sorted order; sampling is deterministic with `--seed`
- The reducer keeps first‑seen conversation ordering and applies a stable decision matrix
- Context list ordering is deterministic (first occurrence)
- Streaming detection only uses the streaming path when input clearly looks like JSONL (see above)

## Enrichment Details

Per‑message mode
- Mode is per user message and comes from `conversation.messageText`.
- We align by primary `headerRequestId` correlation (preferred), and fall back to mapping user message order to `turnIndex`.

Effective model mapping (last message only)
- If last role is assistant: use `baseModel` (fallback to unwrapped `request.option.model`)
- If last role is user/tool/system: use unwrapped `request.option.model`
- Never set a trajectory‑level model; conversations can span multiple engine calls/models

Interactive session model fill (non‑last messages)
- For the same `(sessionId, requestId)` pair, use interactive session model to fill earlier messages in the snapshot.
- Prefer `interactiveSessionResponse` over `interactiveSessionMessage` when both exist.
- Ignore placeholder values like `auto`.
- Set `model_source = 'interactiveSession'` for models sourced from interactive session telemetry.
- If interactive session model disagrees with the engine’s last‑message model for that request, set `model_conflict = True` on the last message (engine remains authoritative).

## Behavioral Notes and Caveats

Mode can change within a conversation
- Each user message can have a different mode (ask → agent → edit). Track `mode_distribution`.

turnIndex semantics
- `turnIndex` is the Nth user message (0‑based), not index in entire message array.

Snapshot vs accumulation
- Each `engine.messages` entry is a discrete LLM API call snapshot, not a cumulative transcript.
- You will see overlapping snapshots for the same conversation; we deduplicate by most messages (then latest timestamp).

Model field mutual exclusivity
- In practice, `baseModel` and `request.option.model` never co‑occur. Treat them as alternative sources.

Assistant tool calls
- Assistant messages can have empty `content` but carry `tool_calls` — keep them.

messagesJson splitting
- Large conversations split into `messagesJson`, `messagesJson_02`, … (supports up to 100 parts). We reconstruct before parsing.

## Examples

conversation.messageText
```json
{
  "name": "GitHub.copilot-chat/conversation.messageText",
  "data": {"baseData": {"properties": {
    "conversationId": "abc-123",
    "mode": "ask",
    "turnIndex": 0,
    "source": "user",
    "messageText": "How do I implement ..."
  }}}
}
```

engine.messages (with model fields)
```json
{
  "name": "GitHub.copilot.chat/engine.messages",
  "data": {"baseData": {"properties": {
    "conversationId": "abc-123",
    "messagesJson": "[ ... ]",
    "baseModel": "gpt-4o-mini"
  }}}
}
```
or
```json
{
  "name": "GitHub.copilot.chat/engine.messages",
  "data": {"baseData": {"properties": {
    "conversationId": "abc-123",
    "messagesJson": "[ ... ]",
    "request.option.model": "\"gpt-4o-mini\""
  }}}
}
```

interactiveSession* (used for earlier message model fill)
```json
{
  "name": "GitHub.copilot-chat/interactiveSessionResponse",
  "data": {"baseData": {"properties": {
    "sessionId": "abc-123",
    "requestId": "rid-001",
    "baseModel": "gpt-4o-mini"
  }}}
}
```

Example trajectory (after enrichment)
```json
{
  "conversation_id": "abc-123",
  "metadata": {"mode": "ask", "timestamp": "..."},
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "...", "mode": "ask", "model": "gpt-4o-mini", "model_source": "interactiveSession"},
    {"role": "assistant", "content": "...", "model": "gpt-4o-mini", "model_source": "engine"}
  ],
  "mode_distribution": {"ask": 1}
}
```

Merged tool metadata (illustrative)
```json
// Earlier snapshot (assistant tool call + tool response)
{"messages": [
  {"role": "assistant", "content": "", "tool_calls": [{
    "id": "toolu_001", "type": "function",
    "function": {"name": "do_something", "arguments": "{\"x\":1}"}
  }]},
  {"role": "tool", "content": "ok", "tool_call_id": "toolu_001"}
]}

// Later snapshot (longer; winner) with no tool metadata
{"messages": [
  {"role": "assistant", "content": "reply"},
  {"role": "user", "content": "next"},
  {"role": "assistant", "content": "ok"}
]}

// After dedupe + merge (role-aware), winner carries tool_calls/tool_call_id when missing
{"messages": [
  {"role": "assistant", "content": "reply", "tool_calls": [{"id":"toolu_001", "type":"function", "function": {"name":"do_something", "arguments":"{\"x\":1}"}}]},
  {"role": "user", "content": "next"},
  {"role": "assistant", "content": "ok"}
]}
```

Note on invariants observed in telemetry
- `baseModel` and `request.option.model` are mutually exclusive per event
- When last role is assistant, `baseModel` is present (response)
- When last role is user/tool, `request.option.model` is present (request)

## Context Fields

Multiple mechanisms exist for attaching context to conversations:

- `attachedContext`: string/array/object with extra context
- `contextTypes`: e.g., none | file | selection | workspace
- `fileExcerpt`: code snippet with line ranges
- `activeSelection`: current editor selection

Message content context (user messages)
- We also scan user message content and collect structured signals under `context.message_contexts`:
  - XML‑style tags: `<environment_info>`, `<workspace_info>`, `<context>`, `<editorContext>`, `<repoContext>`, `<reminderInstructions>`, `<userRequest>` (actual user input lives inside this tag)
  - Attachments and file references
  - Agent mentions like `@workspace`, `@terminal`, `@vscode`
- For convenience, a boolean summary is exposed under `context.message_context` (e.g., `has_environment_info`, `has_workspace_info`, `has_context_info`, etc.).

System‑injected user messages include XML‑like tags, for example:
`<environment_info>`, `<workspace_info>`, `<context>`, `<userRequest>` (actual user input lives inside this tag), `<attachments>`, `<editorContext>`, `<repoContext>`.

## CLI and Validation

Extract trajectories
- `python cli.py extract <path> [--sample N --seed S --regex ...]`
  - By default, only trajectories whose first message is `system` are kept
    (aligns with expected turnIndex semantics). To include all trajectories,
    pass `--require-system-first false`.

Run checks
- Model fields correlation: `python cli.py check model-correlation <path> -v`
- Telemetry type search: `python cli.py check telemetry-type-search <path> --contains engine`

## Data Flow Diagram

```mermaid
graph TD
    A[Telemetry File] --> B{Entry Type?}
    B -->|engine.messages| C[Extract messagesJson]
    B -->|conversation.messageText| D[Track Mode + TurnIndex]
    B -->|interactiveSession Message/Response| E[Collect (sessionId, requestId) -> Model]
    B -->|participantDetectionContext| F[Extract Context]

    C --> F[Reconstruct Split Fields]
    F --> G[Parse JSON Array]
    G --> H[Extract All Roles]

    D --> I[Map Modes via headerRequestId / TurnIndex]
    E --> K[Fill Non-Last Message Models]
    F --> J[Collect Context Fields]

    H --> L[Build Trajectory]
    I --> L
    J --> L
    K --> L

    L --> M[Output: Full Conversation Trajectory]
```

## Related Documentation

- XML tag reference and user-input isolation rules: `docs/VSCODE_XML_TAGS.md`
- Viewer behavior and visualization details (attachments, system-injected context styling): `trajectory-viewer/README.md`

## Developer Notes

This section is for advanced users and contributors. It does not change extraction behavior but helps diagnose differences and performance.

- Compare utilities
  - `telemetry-processor/dev-tools/compare.py`: Compares two JSONL trajectory files by conversation_id. Reports payload vs context diffs, and can deep‑dive a specific id.
  - `telemetry-processor/dev-tools/diff-messages.py`: Prints field‑by‑field differences for a single conversation at a message index.
  - Typical usage:
    - `python telemetry-processor/dev-tools/compare.py old.jsonl new.jsonl` (add `--id <cid>` for a deep dive)
    - `python telemetry-processor/dev-tools/diff-messages.py old.jsonl new.jsonl <cid> --idx N`

- Troubleshooting diffs
  - Recovery differences: old output may have been produced with recovery on; current default is off. Re‑run with `--json-recovery` to align.
  - Dedupe reducer differences: winners are chosen by (messages, timestamp); merged fields include per‑message mode/model and role‑aware tool metadata (default ON). This can enrich winners while keeping selection stable.
  - Context differences: mode in `message_contexts` is populated after correlation; older artifacts may show `None`.
  - Sampling: ensure `--seed` and `--sample-mode` match.

- Performance guidance
  - Default CLI path uses SQLite‑backed dedupe and streaming JSONL correlation for scalability.
  - Leave recovery off unless dealing with corrupted lines; it has CPU cost.
  - Deferred context scan runs once per kept trajectory and does not alter selection.
