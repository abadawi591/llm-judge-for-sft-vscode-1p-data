# SFT Data Curation Pipeline

> **📍 Location:** `telemetry-main/kusto_scripts/data_prep/raw_data_curation_databricks/`
> 
> **🎯 Purpose:** Export 120K curated conversations from Azure Data Explorer (Kusto) to Azure Blob Storage for SFT training.

---

## Quick Start

```bash
# 1. Ensure you're logged in to Azure
az login

# 2. Run the export (ALL splits at once - recommended)
cd ~/coreai/llm_judge
python3 telemetry-main/kusto_scripts/data_prep/raw_data_curation_databricks/notebooks/export_sft_to_blob.py

# Or run in tmux for long-running export:
tmux new-session -d -s sft_export 'cd ~/coreai/llm_judge && python3 telemetry-main/kusto_scripts/data_prep/raw_data_curation_databricks/notebooks/export_sft_to_blob.py 2>&1 | tee sft_export.log; exec bash'
tmux attach -t sft_export
```

**⚠️ Important:** Run WITHOUT `--split` flag to export all splits (train/val/test) in ONE run. This is 3× faster and puts 3× less load on the server than running splits separately.

**Expected time:** ~1.5-2 hours (40 chunks × ~2-3 min each)

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           SFT DATA CURATION PIPELINE                                     │
│                                                                                          │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐      │
│   │    STEP 1    │     │    STEP 2    │     │    STEP 3    │     │    STEP 4    │      │
│   │  Hash-Based  │ ──▶ │   Aggregate  │ ──▶ │  Stratified  │ ──▶ │   Validate   │      │
│   │   Chunking   │     │   & Dedup    │     │   Sampling   │     │   & Upload   │      │
│   └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘      │
│         │                     │                    │                    │               │
│         ▼                     ▼                    ▼                    ▼               │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐      │
│   │ 40 Kusto     │     │ ~300K unique │     │ 120K sampled │     │ Azure Blob   │      │
│   │ queries      │     │ conversations│     │ conversations│     │ Storage      │      │
│   └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘      │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Process

### STEP 1: Hash-Based Chunking

**Why hash-based?** Guarantees each conversation is fully contained in ONE chunk.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           HASH-BASED CHUNKING                                            │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   KQL Filter: where hash(conversationId) % 40 == {chunk_num}                            │
│   Time Window: 15 days (provides ~335k convos, 2.8× the 120k target)                    │
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │  Chunk 0: hash % 40 == 0   (~2.5% of conversations)                             │   │
│   │  ├── Conv_A (all 7 turns) ✅                                                    │   │
│   │  ├── Conv_F (all 3 turns) ✅                                                    │   │
│   │  └── Conv_K (all 12 turns) ✅                                                   │   │
│   ├─────────────────────────────────────────────────────────────────────────────────┤   │
│   │  Chunk 1: hash % 40 == 1                                                        │   │
│   │  ├── Conv_B (all 5 turns) ✅                                                    │   │
│   │  ├── Conv_G (all 9 turns) ✅                                                    │   │
│   │  └── Conv_L (all 4 turns) ✅                                                    │   │
│   ├─────────────────────────────────────────────────────────────────────────────────┤   │
│   │  ...                                                                            │   │
│   ├─────────────────────────────────────────────────────────────────────────────────┤   │
│   │  Chunk 39: hash % 40 == 39                                                      │   │
│   │  └── ...                                                                        │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
│   ✅ GUARANTEE: Each conversation is 100% in exactly ONE chunk                          │
│   ✅ GUARANTEE: Conversation completeness preserved                                     │
│   ✅ GUARANTEE: No cross-chunk conversation splits                                      │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**Query file:** `queries/sft_candidates_hash_chunked.kql`

---

### STEP 2: Aggregate & Deduplicate in Python

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           AGGREGATION IN PYTHON                                          │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   Chunk 0 results ─────┐                                                                │
│   Chunk 1 results ─────┤                                                                │
│   Chunk 2 results ─────┼───▶  [ AGGREGATE ]  ───▶  [ DEDUPLICATE ]  ───▶  300K unique  │
│   ...                  │           │                     │               conversations  │
│   Chunk 39 results ────┘           │                     │                              │
│                                    ▼                     ▼                              │
│                            Combine all             Remove duplicates                    │
│                            chunk results           by conversationId                    │
│                                                                                          │
│   Each record includes:                                                                 │
│   • conversationId, userName                                                            │
│   • turnCount, bucket (short/medium/long)                                              │
│   • turnsArray with full conversation content                                          │
│   • Token metrics (promptTokens, completionTokens, llmCallCount)                       │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### STEP 3: Stratified Sampling in Python

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           STRATIFIED SAMPLING                                            │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   STEP 3a: Assign Split by conversationId Hash                                          │
│   ─────────────────────────────────────────────                                         │
│                                                                                          │
│       hash(conversationId) % 100:                                                       │
│         < 83   ───▶  TRAIN  (83%)                                                       │
│         < 92   ───▶  VAL    (9%)                                                        │
│         >= 92  ───▶  TEST   (8%)                                                        │
│                                                                                          │
│   STEP 3b: Assign Bucket by Turn Count                                                  │
│   ─────────────────────────────────────                                                 │
│                                                                                          │
│       turnCount 3-5   ───▶  short_3_to_5_turns                                          │
│       turnCount 6-10  ───▶  medium_6_to_10_turns                                        │
│       turnCount 11-20 ───▶  long_11_to_20_turns                                         │
│                                                                                          │
│   STEP 3c: Sample from Each Group                                                       │
│   ───────────────────────────────                                                       │
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                              TARGET COUNTS                                       │   │
│   ├─────────────────────────────────────────────────────────────────────────────────┤   │
│   │  SPLIT  │  SHORT (3-5)  │  MEDIUM (6-10)  │  LONG (11-20)  │  TOTAL            │   │
│   │─────────┼───────────────┼─────────────────┼────────────────┼───────────────────│   │
│   │  TRAIN  │    40,000     │     40,000      │    20,000      │  100,000          │   │
│   │  VAL    │     4,000     │      4,000      │     2,000      │   10,000          │   │
│   │  TEST   │     4,000     │      4,000      │     2,000      │   10,000          │   │
│   ├─────────┼───────────────┼─────────────────┼────────────────┼───────────────────┤   │
│   │  TOTAL  │    48,000     │     48,000      │    24,000      │  120,000          │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### STEP 4: Validate & Upload

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           VALIDATION & UPLOAD                                            │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │  PER-RECORD VALIDATION                                                          │   │
│   │  ─────────────────────                                                          │   │
│   │  ✓ Required fields present (conversationId, userName, bucket, turnsArray)      │   │
│   │  ✓ Split hash verification (conversationId maps to correct split)              │   │
│   │  ✓ Conversation completeness (first turn = index 1)                            │   │
│   │  ✓ Turn indices sequential (1, 2, 3... no gaps)                                │   │
│   │  ✓ Turn count matches bucket (short=3-5, medium=6-10, long=11-20)              │   │
│   │  ✓ userMessage non-empty in every turn                                         │   │
│   │  ✓ Token sanity (promptTokens > 0, completionTokens >= 0)                      │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │  CROSS-SPLIT VALIDATION                                                         │   │
│   │  ─────────────────────────                                                      │   │
│   │  ✓ No duplicate conversationIds within a split                                 │   │
│   │  ✓ No conversationId appears in multiple splits (mutual exclusivity)           │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │  UPLOAD TO AZURE BLOB                                                           │   │
│   │  ───────────────────────                                                        │   │
│   │                                                                                 │   │
│   │  vscodedata_120k_complete_stratified_deduped_60d_20241209_143052/              │   │
│   │  ├── train/                                                                     │   │
│   │  │   ├── short_3_to_5_turns.json      (40,000 records)                         │   │
│   │  │   ├── medium_6_to_10_turns.json    (40,000 records)                         │   │
│   │  │   └── long_11_to_20_turns.json     (20,000 records)                         │   │
│   │  ├── val/                                                                       │   │
│   │  │   ├── short_3_to_5_turns.json      (4,000 records)                          │   │
│   │  │   ├── medium_6_to_10_turns.json    (4,000 records)                          │   │
│   │  │   └── long_11_to_20_turns.json     (2,000 records)                          │   │
│   │  ├── test/                                                                      │   │
│   │  │   ├── short_3_to_5_turns.json      (4,000 records)                          │   │
│   │  │   ├── medium_6_to_10_turns.json    (4,000 records)                          │   │
│   │  │   └── long_11_to_20_turns.json     (2,000 records)                          │   │
│   │  ├── metadata.json                                                              │   │
│   │  └── invalid_records_*.json           (if any validation failures)             │   │
│   │                                                                                 │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Login to Azure
az login

# 3. Run production export (all splits)
cd telemetry-main/kusto_scripts/data_prep/raw_data_curation_databricks
python notebooks/export_sft_to_blob.py

# Or run a specific split
python notebooks/export_sft_to_blob.py --split train
python notebooks/export_sft_to_blob.py --split val
python notebooks/export_sft_to_blob.py --split test

# Test mode (~100 records)
python notebooks/export_sft_to_blob.py --test
```

### Running in Background (Recommended for Production)

```bash
# Start in tmux for persistence
tmux new-session -d -s sft_export 'python -u notebooks/export_sft_to_blob.py 2>&1 | tee export.log'

# Attach to watch progress
tmux attach -t sft_export

# Detach: Ctrl+B, then D
```

---

## Folder Structure

```
raw_data_curation_databricks/
├── README.md                                    # This file
├── requirements.txt                             # Python dependencies
├── queries/
│   ├── sft_candidates_hash_chunked.kql         # ⭐ Main production query (hash-based chunking)
│   ├── sft_test_100_with_trajectory.kql        # Test query with full details
│   └── sft_test_100_lite.kql                   # Lightweight test (no trajectory)
└── notebooks/
    └── export_sft_to_blob.py                   # Export script
```

---

## Configuration

Key settings in `export_sft_to_blob.py`:

```python
# Time window
# 15 days chosen for safe buffer (Dec 2024):
#   - 15 days yields ~335k bucketed convos total (2.8× the 120k target)
#   - All buckets have 2× or more buffer for stratified sampling
#   - 60 days caused server timeouts (>10 min per chunk)
TIME_WINDOW = "ago(15d)"

# Chunking
# 40 chunks to reduce per-chunk data size and avoid server timeouts
# Each chunk = 2.5% of all conversations (hash % 40)
NUM_HASH_CHUNKS = 40

# Sample sizes
SAMPLE_SIZES = {
    "production": {
        "train": {"short": 40000, "medium": 40000, "long": 20000},  # 100k
        "val":   {"short": 4000,  "medium": 4000,  "long": 2000},   # 10k
        "test":  {"short": 4000,  "medium": 4000,  "long": 2000},   # 10k
    }
}

# Split assignment
# hash(conversationId) % 100:
#   < 83  → train
#   < 92  → val
#   >= 92 → test

# Timeouts
SERVER_TIMEOUT_SECONDS = 1800  # 30 minutes per chunk
CLIENT_TIMEOUT_SECONDS = 2100  # 35 minutes client-side
```

---

## Data Quality Guarantees

| Guarantee | How It's Ensured |
|-----------|------------------|
| **Complete conversations** | KQL filter: `minTurnIndex == 1 AND turnCount == maxTurnIndex` |
| **No split contamination** | Hash-based splitting: same conversationId always same split |
| **Conversation integrity** | Hash-based chunking: entire conversation in one chunk |
| **Stratified balance** | Python sampling: exact counts per bucket per split |
| **Agent mode only** | KQL filter: `mode == "agent"` |
| **Deduplicated** | Python dedup by conversationId after aggregation |

---

## Validation Details

### Per-Record Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Required fields | ❌ Fatal | `conversationId`, `userName`, `bucket`, `turnsArray` |
| Split hash | ❌ Fatal | conversationId hashes to expected split |
| Completeness | ❌ Fatal | First turn has `turnIndex = 1` |
| Sequential turns | ❌ Fatal | Indices are 1, 2, 3... (no gaps) |
| Bucket match | ❌ Fatal | Turn count matches bucket range |
| User message | ❌ Fatal | Every turn has non-empty userMessage |
| Model message | ⚠️ Warning | Can be empty for tool-only responses |
| Token sanity | ⚠️ Warning | promptTokens > 0, completionTokens >= 0 |

### Invalid Records Output

Failed records are saved for debugging:

```json
// invalid_records_train_20241209_143052.json
{
  "summary": {
    "total_invalid": 153,
    "error_summary": {"Bucket mismatch: short bucket has 6 turns": 45}
  },
  "invalid_records": [
    {"conversationId": "abc123", "bucket": "short", "turnCount": 6, "errors": [...]}
  ]
}
```

---

## Azure Resources

### Kusto Cluster
```
Cluster:  https://ade.loganalytics.io/subscriptions/d0c05057-7972-46ff-9bcf-3c932250155e/...
Database: d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2
```

### Blob Storage
```
Account:   githubtelemetry
Container: github-copilot-sft-data-all-languages
Path:      experiments/testvscode_test/v4/
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [Data Schema](../../vscode_1p_queries/docs/vscode_1p_data_team_docs/understand_data_schema/01_DATA_SCHEMA.md) | Conversation structure, event types |
| [Token Telemetry](../../vscode_1p_queries/docs/vscode_1p_data_team_docs/understand_data_schema/02_TOKEN_TELEMETRY.md) | Token mechanics, truncation |
| [LLM Judge Strategies](../sft_example_pareesa/LABELING_APPROACHES_DETAILED.md) | Labeling approaches for SFT |
