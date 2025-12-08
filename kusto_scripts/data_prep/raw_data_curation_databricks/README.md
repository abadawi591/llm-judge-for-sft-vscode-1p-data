# SFT Data Curation Pipeline

This pipeline curates raw conversation data from VS Code Copilot telemetry for SFT training.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SFT DATA CURATION PIPELINE                               │
│                                                                                  │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────────────────────────┐  │
│  │   Kusto     │ ───▶ │  Databricks │ ───▶ │  Azure Blob Storage             │  │
│  │   (ADX)     │      │  (Process)  │      │  github-copilot-sft-data-...    │  │
│  └─────────────┘      └─────────────┘      └─────────────────────────────────┘  │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Target Output

**Total: ~100,000 complete conversations** for SFT training, stratified by turn count:

| Bucket | Turn Range | Sample Size |
|--------|------------|-------------|
| `short_3_to_5_turns` | 3-5 turns | 40,000 |
| `medium_6_to_10_turns` | 6-10 turns | 40,000 |
| `long_11_to_20_turns` | 11-20 turns | 20,000 |

## Data Quality Guarantees

✅ **Complete conversations only** - `minTurnIndex == 1` AND `capturedTurnCount == maxTurnIndex`  
✅ **Deduplicated** - `arg_max(strlen(messageText)) by conversationId, messageId, source`  
✅ **Agent mode only** - `mode == "agent"`  
✅ **Stratified sampling** - Balanced representation across conversation lengths

---

## Folder Structure

```
raw_data_curation_databricks/
├── README.md                           # This file
├── queries/
│   ├── sft_test_100.kql               # Small test query (~100 records, 1d window)
│   └── sft_100k_production.kql        # Full production query (100k records, 60d window)
└── notebooks/
    └── export_sft_to_blob.py          # Databricks notebook for export
```

---

## Kusto Cluster

```
Cluster: https://ade.loganalytics.io/subscriptions/d0c05057-7972-46ff-9bcf-3c932250155e/resourceGroups/CopilotChatEval/providers/Microsoft.OperationalInsights/workspaces/d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2

Database: d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2
```

---

## Azure Blob Storage

**Container:** `github-copilot-sft-data-all-languages`  
**Storage Account:** `githubtelemetry`  
**Path:** `experiments/testvscode_test/v4/`

### Output Structure

```
github-copilot-sft-data-all-languages/
└── experiments/
    └── testvscode_test/
        └── v4/
            └── vscodedata_100k_complete_stratified_deduped_60d_YYYYMMDD/
                ├── short_3_to_5_turns.json         # 40k records
                ├── medium_6_to_10_turns.json       # 40k records
                ├── long_11_to_20_turns.json        # 20k records
                └── metadata.json                   # Curation metadata
```

---

## Usage

### 1. Test Query (for ADX Web UI)

Run `queries/sft_test_100.kql` in Azure Data Explorer to verify the query works:
- Time window: 1 day
- Sample sizes: 40 / 40 / 20 (~100 total)

### 2. Production Query (via Databricks)

The full 100k query should be run via Databricks due to memory constraints in ADX Web UI.

```bash
# Login to Azure first
az login

# Run the Databricks notebook
# (See notebooks/export_sft_to_blob.py)
```

---

## Query Versions

| Version | File | Time Window | Samples | Use Case |
|---------|------|-------------|---------|----------|
| Test | `sft_test_100.kql` | ago(1d) | ~100 | Quick ADX testing |
| Production | `sft_100k_production.kql` | ago(60d) | 100k | Full SFT data |

---

## Metadata Schema

Each export includes a `metadata.json`:

```json
{
  "curation_info": {
    "curation_date": "2024-12-08T12:00:00Z",
    "curation_id": "vscodedata_100k_complete_stratified_deduped_60d_20241208",
    "query_file": "sft_100k_production.kql",
    "data_source": "vscode_1p_agent_mode"
  },
  "query_parameters": {
    "time_window": "ago(60d) to now()",
    "cluster": "https://ade.loganalytics.io/...",
    "database": "d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2"
  },
  "completeness_criteria": {
    "minTurnIndex_equals": 1,
    "capturedTurnCount_equals_maxTurnIndex": true,
    "mode": "agent"
  },
  "deduplication": {
    "method": "arg_max(strlen(messageText)) by conversationId, messageId, source",
    "description": "Keep longest message text for each (conversationId, messageId, source) triple"
  },
  "stratification": {
    "short_3_to_5_turns": { "turn_range": [3, 5], "target_count": 40000 },
    "medium_6_to_10_turns": { "turn_range": [6, 10], "target_count": 40000 },
    "long_11_to_20_turns": { "turn_range": [11, 20], "target_count": 20000 },
    "total_target": 100000
  },
  "actual_counts": {
    "short_3_to_5_turns": null,
    "medium_6_to_10_turns": null,
    "long_11_to_20_turns": null,
    "total": null
  },
  "output_files": {
    "short_3_to_5_turns": "short_3_to_5_turns.json",
    "medium_6_to_10_turns": "medium_6_to_10_turns.json",
    "long_11_to_20_turns": "long_11_to_20_turns.json"
  }
}
```

---

## Related Documentation

- [Data Schema Documentation](../../vscode_1p_queries/docs/vscode_1p_data_team_docs/understand_data_schema/README.md)
- [Token Telemetry](../../vscode_1p_queries/docs/vscode_1p_data_team_docs/understand_data_schema/02_TOKEN_TELEMETRY.md)

