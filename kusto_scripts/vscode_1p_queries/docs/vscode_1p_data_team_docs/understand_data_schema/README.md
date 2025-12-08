# Copilot Agent Mode Telemetry Documentation

This folder contains comprehensive documentation for understanding GitHub Copilot (VS Code) agent mode telemetry data.

---

## Documentation Index

| Document | Description |
|----------|-------------|
| [**01_DATA_SCHEMA.md**](./01_DATA_SCHEMA.md) | **Start here!** Conversation structure, hierarchy, event types, and stratified sampling |
| [**02_TOKEN_TELEMETRY.md**](./02_TOKEN_TELEMETRY.md) | Deep dive into token tracking, trajectories, truncation detection |

---

## Quick Reference

### Conversation Hierarchy

```
CONVERSATION (conversationId)
    │
    ├── TURN 1 (messageId)
    │   ├── LLM Call 1 (callIndex: 1)
    │   ├── LLM Call 2 (callIndex: 2)
    │   └── LLM Call 3 (callIndex: 3)
    │
    ├── TURN 2 (messageId)
    │   ├── LLM Call 1 (callIndex: 1)
    │   └── LLM Call 2 (callIndex: 2)
    │
    └── TURN N (messageId)
        └── LLM Call 1 (callIndex: 1)
```

### Token Fields at a Glance

| Field | Source | Always Available? | Use For |
|-------|--------|-------------------|---------|
| `promptTokens` | LLM API | ✅ Yes | Cost analysis |
| `completionTokens` | LLM API | ✅ Yes | Cost analysis |
| `systemTokens` | Copilot estimate | ⚠️ If hasTrajectory=true | Analysis |
| `userTokens` | Copilot estimate | ⚠️ If hasTrajectory=true | Analysis |
| `assistantTokens` | Copilot estimate | ⚠️ If hasTrajectory=true | Analysis |
| `toolResultTokens` | Copilot estimate | ⚠️ If hasTrajectory=true | Analysis |
| `exceededWindow` | Calculated | ⚠️ If hasTrajectory=true | Truncation detection |

### Stratified Sampling Buckets (Target: ~100k for SFT)

| Bucket | Turn Range | Sample Size |
|--------|------------|-------------|
| `short_3_to_5_turns` | 3-5 | 40,000 |
| `medium_6_to_10_turns` | 6-10 | 40,000 |
| `long_11_to_20_turns` | 11-20 | 20,000 |

**Total: 100,000 conversations**

---

## Visual Assets

All diagrams are in the `assets/` folder:

| File | Description |
|------|-------------|
| `00_conversation_hierarchy (1).svg` | High-level conversation hierarchy |
| `conversation_summary.svg` | Conversation structure summary |
| `conversation_enhanced (1).svg` | Detailed conversation structure |
| `01_token_data_flow.svg` | INPUT vs OUTPUT token flow |
| `02_trajectory.svg` | What is a trajectory |
| `03_token_behavior.svg` | Constant vs growing fields |
| `04_baseline_tokens.svg` | Why first call has ~20K tokens |
| `05_user_turn.svg` | Why userTokens is constant |
| `06_tokenizer_diff.svg` | Copilot vs LLM tokenizers |
| `07_truncation.svg` | When truncation occurs |
| `08_truncation_priority.svg` | What gets dropped first |
| `09_system_across_turns.svg` | System tokens consistency |
| `10_system_across_convos.svg` | System tokens variance |
| `11_telemetry_events.svg` | Telemetry events overview |
| `12_event_timing.svg` | Event timing within a turn |

---

## Related Production Queries

```
production/final/
├── sft_stratified_final.kql       # Stratified sampling with full token breakdown
├── sft_simple_final.kql           # Lightweight (no trajectory parsing)
└── sft_with_trajectory_final.kql  # Full per-call trajectory breakdown
```

See [production/final/README.md](../../../production/final/README.md) for usage guidance.
