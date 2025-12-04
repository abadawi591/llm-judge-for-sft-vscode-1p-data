# Agent Mode SFT Data Extraction Guide

> **Purpose:** This is a guide for extracting agent mode conversation data from VS Code Copilot telemetry for SFT (Supervised Fine-Tuning) training.  
> **Last Updated:** 2025-12-03  
> **Owner:** Ahmed Badawi

---

## 📋 Documentation Index

| Document | Description |
|----------|-------------|
| **[01_DATA_STRUCTURE.md](docs/01_DATA_STRUCTURE.md)** | Data hierarchy, field definitions, sample conversation |
| **[02_ROUTING_STRATEGIES.md](docs/02_ROUTING_STRATEGIES.md)** | Session-based vs conversation-aware routing |
| **[03_DATA_BALANCING.md](docs/03_DATA_BALANCING.md)** | Balancing strategies for SFT training |
| **[04_QUERY_REFERENCE.md](docs/04_QUERY_REFERENCE.md)** | All query files and their purposes |
| **[05_DATA_QUIRKS.md](docs/05_DATA_QUIRKS.md)** | Known issues and solutions |

---

## 🚀 Quick Start

### For Session-Based Router Training
```
1. Run: production/sft_session_router_first_turns.kql
2. Get: ~300k first-turn samples with complexity signals
3. Send to LLM-Judge for reasoning/non-reasoning annotation
4. Balance to 100k samples (50:50 or 70:30)
```

### For Conversation-Aware Router Training
```
1. Run: production/sft_stratified_by_turn_count.kql
2. Get: ~25k complete conversations stratified by length
3. Flatten to individual turns
4. Send to LLM-Judge for per-turn annotation
5. Balance to 100k samples
```

### For Complete Conversations (3-10 turns)
```
1. Run: production/sft_complete_conversations_3to10.kql
2. Get: Complete conversations with reliable promptTokenDelta
3. Includes: isComplete flag, all token metrics
```

---

## 🎯 Project Goal

Train a **BERT classifier** to route user messages between:

| Label | Model Type | When to Use |
|-------|------------|-------------|
| **0** | Reasoning | Complex tasks requiring deep thinking |
| **1** | Non-reasoning | Simple tasks, quick responses |

**Target:** 100k balanced SFT samples with 50:50 and 70:30 reasoning ratio.

---

## 📁 Folder Structure

```
vscode_1p_queries/
├── AGENT_SFT_DATA_GUIDE.md              # 📖 This file (index)
├── docs/                                 # 📚 Detailed documentation
│   ├── 01_DATA_STRUCTURE.md             # Data hierarchy & definitions
│   ├── 02_ROUTING_STRATEGIES.md         # Routing approaches
│   ├── 03_DATA_BALANCING.md             # Balancing strategies
│   ├── 04_QUERY_REFERENCE.md            # Query catalog
│   └── 05_DATA_QUIRKS.md                # Known issues
│
├── production/                           # ⭐ DATA EXTRACTION QUERIES
│   ├── sft_nested_json.kql              # Full nested JSON with deltas
│   ├── sft_nested_json_simple.kql       # Simple (no delta calculation)
│   ├── sft_complete_conversations_3to10.kql    # Complete convos only
│   ├── sft_session_router_first_turns.kql      # First turns for session routing
│   └── sft_stratified_by_turn_count.kql        # Stratified by turn count
│
├── exploration/                          # Investigation queries
│   ├── discover_events.kql
│   ├── message_schema.kql
│   ├── token_schema.kql
│   ├── tool_schema.kql
│   ├── exact_tool_tokens.kql
│   └── model_switching.kql
│
└── verification/                         # Verification queries
    ├── token_accumulation.kql
    ├── numRequests_formula.kql
    └── delta_accuracy.kql
```

---

## 🔑 Key Concepts (Summary)

For detailed explanations with visuals, see **[01_DATA_STRUCTURE.md](docs/01_DATA_STRUCTURE.md)**.

### Hierarchy

```
CONVERSATION (conversationId)
    └── TURN 1 (messageId, turnIndex: 1)
          ├── User Message (1)
          └── Model Turn (1+ LLM calls)
                ├── LLM Call 1 (tool-use or text)
                ├── LLM Call 2 (tool-use or text)
                └── LLM Call N (final response)
    └── TURN 2 (messageId, turnIndex: 2)
          └── ...
```

### Key Fields

| Field | Description |
|-------|-------------|
| `conversationId` | Unique chat session identifier |
| `turnIndex` | Turn number (1-indexed) |
| `messageId` | Turn identifier |
| `llmCalls` | Array of LLM API calls in this turn |
| `promptTokens` | **Cumulative** context tokens per call |
| `promptTokenDelta` | **Calculated** tokens added (only reliable for complete convos) |
| `numRequests` | LLM calls = sum(toolCounts) + 1 |
| `toolCounts` | JSON of tools used: `{"read_file":2}` |
| `isComplete` | True if `minTurnIndex==1 AND capturedTurnCount==maxTurnIndex` |

### Completeness Matters

`promptTokenDelta` is **only reliable** when `isComplete: true`. For partial captures, the first turn's delta is inflated.

---

## 📊 Query Selection Guide

| Your Goal | Use This Query |
|-----------|----------------|
| Session-based routing training | `sft_session_router_first_turns.kql` |
| Conversation-aware routing training | `sft_stratified_by_turn_count.kql` |
| Complete conversations with all metrics | `sft_complete_conversations_3to10.kql` |
| Quick extraction, no delta calculation | `sft_nested_json_simple.kql` |
| Full data with partial conversations | `sft_nested_json.kql` |

---

## 📈 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SFT DATA PIPELINE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────┐│
│  │   KUSTO      │    │  LLM-JUDGE   │    │   BALANCE    │    │    SFT     ││
│  │   QUERIES    │───▶│  ANNOTATION  │───▶│   DATASET    │───▶│  TRAINING  ││
│  │              │    │              │    │              │    │            ││
│  │  ~300k raw   │    │  0: reasoning│    │  50:50 or    │    │  BERT      ││
│  │  samples     │    │  1: non-reas │    │  70:30 ratio │    │  Classifier││
│  └──────────────┘    └──────────────┘    └──────────────┘    └────────────┘│
│                                                                              │
│  This repo ──────────▶ Your annotation ──▶ Python balance ──▶ Training     │
│                        pipeline           scripts           infrastructure  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🖼️ Diagram Placeholders

The following SVG diagrams can be added:

| Placeholder | Location | Description |
|-------------|----------|-------------|
| `conversation_hierarchy.svg` | [01_DATA_STRUCTURE.md](docs/01_DATA_STRUCTURE.md) | Conversation → Turn → LLM Calls |
| `session_routing_flow.svg` | [02_ROUTING_STRATEGIES.md](docs/02_ROUTING_STRATEGIES.md) | Session routing decision flow |
| `pipeline_overview.svg` | This file | Full data pipeline |

---

## 📝 Changelog

| Date | Changes |
|------|---------|
| 2025-12-03 | Split guide into multiple focused documents |
| 2025-12-03 | Added Part 6: Data Balancing Strategies |
| 2025-12-03 | Added completeness guarantee and reliable promptTokenDelta |
| 2025-12-03 | Initial guide created |
