# GPT-5.2 Soft Label Teacher

A modular async Python package for binary classification with soft-label generation
using Azure OpenAI with logprobs and logit_bias.

## Task Description

**Binary Classification**: "Does this user message require reasoning?"

| Label | Token | Meaning | Examples |
|-------|-------|---------|----------|
| 0 | `"0"` | **REQUIRES reasoning** | Complex refactoring, architecture decisions, multi-step debugging |
| 1 | `"1"` | **Does NOT require reasoning** | Simple syntax, code snippets, basic explanations |

## Key Features

- **Per-turn labeling**: Each user message in a conversation gets its own label
- **Soft labels**: Probability in [0, 1] derived from logprobs
- **Rationales by default**: Human-readable explanations (use `--no-rationales` to disable)
- **Modular strategies**: Plug-in system for what the LLM sees
- **Azure Blob input**: Read directly from blob storage
- **Tenacity retry**: Robust retry with exponential backoff
- **Rate limit aware**: Semaphore=50 based on gpt-5.2 deployment limits

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GPT-5.2 SOFT LABEL TEACHER                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐     │
│  │  config.py  │   │  client.py  │   │ tokenizer.py│   │  prompts.py │     │
│  ├─────────────┤   ├─────────────┤   ├─────────────┤   ├─────────────┤     │
│  │ • Rate lims │   │ • Azure OAI │   │ • tiktoken  │   │ • System    │     │
│  │ • Retry cfg │   │ • Key Vault │   │ • Token IDs │   │ • Templates │     │
│  │ • Semaphore │   │ • tenacity  │   │ • Encoding  │   │ • Formatting│     │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘     │
│         │                 │                 │                 │             │
│         └─────────────────┴────────┬────────┴─────────────────┘             │
│                                    │                                        │
│                                    ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         classifier.py                                  │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │  │  classify_message()                                             │  │ │
│  │  │    • API call with logit_bias + logprobs                        │  │ │
│  │  │    • tenacity retry (exp backoff, 5 attempts)                   │  │ │
│  │  │    • Extract soft_label = P("1") / (P("0") + P("1"))            │  │ │
│  │  └─────────────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│         ┌──────────────────────────┼──────────────────────────┐             │
│         │                          │                          │             │
│         ▼                          ▼                          ▼             │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐         │
│  │rationale.py │          │ pipeline.py │          │   cli.py    │         │
│  ├─────────────┤          ├─────────────┤          ├─────────────┤         │
│  │ • Default ON│          │ • Semaphore │          │ • argparse  │         │
│  │ • tenacity  │          │ • Async     │          │ • label     │         │
│  │ • Separate  │          │ • Progress  │          │ • info      │         │
│  │   call      │          │ • Stats     │          │ • test      │         │
│  └─────────────┘          └─────────────┘          └─────────────┘         │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                              io/                                       │ │
│  │  blob_reader.py : Read from Azure Blob Storage                        │ │
│  │  schemas.py     : TurnRecord, LabeledTurnRecord, ConversationRecord   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                           strategies/                                  │ │
│  │  base.py              : Abstract LabelingStrategy interface           │ │
│  │  user_message_only.py : Strategy A - classify message in isolation    │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
                         AZURE BLOB STORAGE
                    (github-copilot-sft-data-all-languages)
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           io/blob_reader.py                                │
│  download_split("train", dataset_name)                                     │
│    → List[ConversationRecord]                                              │
│  flatten_to_turns(conversations)                                           │
│    → List[TurnRecord]                                                      │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                      List[TurnRecord]
                   Each turn = one user message
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           strategies/                                       │
│  UserMessageOnlyStrategy.apply(turn)                                        │
│    → StrategyResult(text_to_classify=turn.user_message)                     │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                       text_to_classify
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          pipeline.py                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  FOR EACH TURN (async, semaphore=50):                                 │  │
│  │                                                                       │  │
│  │  1. classify_message(text_to_classify)                               │  │
│  │     ┌─────────────────────────────────────────────────────────────┐  │  │
│  │     │  AZURE OPENAI API CALL (with tenacity retry)                │  │  │
│  │     │  • max_tokens=1                                             │  │  │
│  │     │  • logprobs=True, top_logprobs=5                            │  │  │
│  │     │  • logit_bias={15: 5.0, 16: 5.0}                            │  │  │
│  │     │  • temperature=1.0                                          │  │  │
│  │     └─────────────────────────────────────────────────────────────┘  │  │
│  │                                                                       │  │
│  │  2. Extract hard_label from generated token                          │  │
│  │  3. Compute soft_label = P("1") / (P("0") + P("1"))                  │  │
│  │                                                                       │  │
│  │  4. generate_rationale(text, label)  [DEFAULT: enabled]              │  │
│  │     ┌─────────────────────────────────────────────────────────────┐  │  │
│  │     │  SEPARATE API CALL (with tenacity retry)                    │  │  │
│  │     │  • max_tokens=128                                           │  │  │
│  │     │  • temperature=0.7                                          │  │  │
│  │     └─────────────────────────────────────────────────────────────┘  │  │
│  │                                                                       │  │
│  │  5. Return LabeledTurnRecord                                         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                          OUTPUT JSONL
                     (one line per turn)
```

## Output Schema

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          OUTPUT JSONL SCHEMA                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  {                                                                          │
│    "conversationId": "abc-123-def",      // Links to original data         │
│    "messageId": "msg-456-xyz",           // Specific turn identifier       │
│    "split": "train",                     // Data split (train/val/test)    │
│    "bucket": "short_3_to_5_turns",       // Stratification bucket          │
│    "hard_label": 0,                      // 0=reasoning, 1=non-reasoning   │
│    "soft_label": 0.23,                   // P(non-reasoning) in [0, 1]     │
│    "rationale": "This message asks..."  // Human-readable explanation     │
│  }                                                                          │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  FIELD DESCRIPTIONS:                                                        │
│                                                                             │
│  IDENTIFIERS (for joining with original data):                              │
│    conversationId + messageId = Unique key                                  │
│                                                                             │
│  PROVENANCE (NOT passed to LLM judge):                                      │
│    split  : Data partition (train/val/test)                                 │
│    bucket : Stratification tier by conversation length                      │
│             • short_3_to_5_turns                                            │
│             • medium_6_to_10_turns                                          │
│             • long_11_to_20_turns                                           │
│                                                                             │
│  LABELS:                                                                    │
│    hard_label (int):                                                        │
│      - 0: Message REQUIRES reasoning (complex, multi-step)                  │
│      - 1: Message does NOT require reasoning (simple, pattern-matching)     │
│                                                                             │
│    soft_label (float):                                                      │
│      Probability of label 1 (non-reasoning) in [0, 1]                       │
│      - 0.0: Definitely requires reasoning                                   │
│      - 0.5: Uncertain                                                       │
│      - 1.0: Definitely does not require reasoning                           │
│      NOTE: P(reasoning) = 1 - soft_label                                    │
│                                                                             │
│  EXPLANATION:                                                               │
│    rationale (str):                                                         │
│      Human-readable explanation (2-4 sentences)                             │
│      Generated by default, disable with --no-rationales                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Blob Storage Organization

### Input (RAW) Data Structure

```
Container: github-copilot-sft-data-all-languages
└── experiments/testvscode_test/v4/
    └── vscodedata_120k_complete_stratified_deduped_60d_YYYYMMDD/  ← RAW
        ├── train/
        │   ├── short_3_to_5_turns.json      (40k conversations)
        │   ├── medium_6_to_10_turns.json    (40k conversations)
        │   └── long_11_to_20_turns.json     (20k conversations)
        ├── val/
        │   ├── short_3_to_5_turns.json      (4k conversations)
        │   ├── medium_6_to_10_turns.json    (4k conversations)
        │   └── long_11_to_20_turns.json     (2k conversations)
        ├── test/
        │   ├── short_3_to_5_turns.json      (4k conversations)
        │   ├── medium_6_to_10_turns.json    (4k conversations)
        │   └── long_11_to_20_turns.json     (2k conversations)
        └── metadata.json
```

### Output (LABELED) Data Structure

⚠️ **SAFETY PRINCIPLE: We NEVER touch the RAW data folder.**
We create a parallel folder with `LABELED_` prefix at the same level.

```
Container: github-copilot-sft-data-all-languages
└── experiments/testvscode_test/v4/
    │
    ├── vscodedata_120k_..._YYYYMMDD/              ← RAW (READ ONLY)
    │   └── (original structure preserved)
    │
    └── LABELED_vscodedata_120k_..._YYYYMMDD/      ← NEW (WRITE)
        ├── train/
        │   ├── short_3_to_5_turns.jsonl           ← Per-turn labels
        │   ├── medium_6_to_10_turns.jsonl
        │   └── long_11_to_20_turns.jsonl
        ├── val/
        │   ├── short_3_to_5_turns.jsonl
        │   ├── medium_6_to_10_turns.jsonl
        │   └── long_11_to_20_turns.jsonl
        ├── test/
        │   ├── short_3_to_5_turns.jsonl
        │   ├── medium_6_to_10_turns.jsonl
        │   └── long_11_to_20_turns.jsonl
        └── labeling_metadata.json
```

### Why This Approach?

| Property | Benefit |
|----------|---------|
| **No modifications to RAW** | Zero risk of data loss/corruption |
| **No copy/move operations** | Avoids mid-transfer failures |
| **LABELED_ prefix** | Clear naming, easy discovery |
| **Mirrored structure** | Same split/bucket organization |
| **Easy joins** | Parallel paths enable simple matching |

### File Format Difference

| Folder | Format | Content |
|--------|--------|---------|
| RAW | `.json` | Array of conversations (nested turns) |
| LABELED | `.jsonl` | One line per **turn** (flattened) |

## Tokenizer Explained

### What's a Token?
LLMs see text as **tokens** — chunks that might be words, parts of words, or characters:
```
"Hello world" → ["Hello", " world"] → Token IDs: [9906, 1917]
"0"           → ["0"]               → Token ID: [15]
"1"           → ["1"]               → Token ID: [16]
```

### Why Token IDs?
The `logit_bias` API parameter requires token IDs (integers), not strings:
```python
# We need to boost tokens "0" and "1"
logit_bias = {15: 5.0, 16: 5.0}  # Token IDs, not strings!
```

### How We Get Them
We use `tiktoken` (OpenAI's tokenizer):
```python
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")  # GPT-4/5 encoding
enc.encode("0")  # Returns [15]
enc.encode("1")  # Returns [16]
```

## Semaphore & Rate Limits

### Why Semaphores with Async?

**Async ≠ Concurrency Control**

Async allows non-blocking I/O, but doesn't limit how many requests we start:

```python
# WITHOUT semaphore: All 100k requests start at once → RATE LIMIT ERROR
tasks = [call_api(msg) for msg in messages]
await asyncio.gather(*tasks)  # 💥

# WITH semaphore: Only 50 run at a time
semaphore = asyncio.Semaphore(50)
async with semaphore:
    await call_api(msg)  # ✅
```

### Rate Limit Analysis for gpt-5.2 Deployment

**Azure OpenAI Deployment Limits (Global Standard tier):**

| Limit | Value |
|-------|-------|
| Requests per minute (RPM) | 10,000 |
| Tokens per minute (TPM) | 1,000,000 |

**Token Usage per Request:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CLASSIFICATION CALL                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  System prompt .......................... ~100 tokens                       │
│  User message (avg) ..................... ~100 tokens                       │
│  Output (max_tokens=1) .................. 1 token                           │
│  ───────────────────────────────────────────────────                        │
│  TOTAL ≈ 200 tokens/request                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  RATIONALE CALL (separate request)                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  System prompt .......................... ~50 tokens                        │
│  User message + label ................... ~100 tokens                       │
│  Output (max_tokens=128) ................ ~100 tokens avg                   │
│  ───────────────────────────────────────────────────                        │
│  TOTAL ≈ 250 tokens/request                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  COMBINED (with rationales enabled) ≈ 450 tokens/turn                       │
│  CLASSIFICATION ONLY ≈ 200 tokens/turn                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Rate Limit Math:**

```
MODE 1: Classification Only (--no-rationales)
─────────────────────────────────────────────
Token limit:    1,000,000 TPM ÷ 200 tokens = 5,000 req/min
Request limit:  10,000 RPM
Bottleneck:     Request limit (can do 10K/min)
Safe rate:      ~5,000 req/min (50% headroom)

With 50 concurrent + ~0.6s latency:
  50 concurrent × (60s ÷ 0.6s) = 5,000 req/min ✓


MODE 2: With Rationales (default)
─────────────────────────────────
2 API calls per turn: classify + rationale
Tokens per turn:  ~450 tokens
Token limit:      1,000,000 TPM ÷ 450 = 2,222 turns/min
Request limit:    10,000 RPM ÷ 2 = 5,000 turns/min
Bottleneck:       Token limit (2,222 turns/min)
Safe rate:        ~1,500 turns/min (30% headroom)

With 50 concurrent + ~2s total latency (both calls):
  50 concurrent × (60s ÷ 2s) = 1,500 turns/min ✓
```

**Semaphore Selection:**

| Concurrency | Classification Only | With Rationales |
|-------------|---------------------|-----------------|
| 20 | ~2,000/min | ~600/min |
| **50** | **~5,000/min** | **~1,500/min** |
| 100 | ~10,000/min (risky) | ~3,000/min (risky) |

**Recommendation: semaphore=50** (default)
- Safe for both modes
- 30-50% headroom for latency spikes
- Tenacity retry handles 429 errors gracefully

**Estimated Processing Time (120K turns):**

| Mode | Rate | Time |
|------|------|------|
| Classification only | 5,000/min | ~24 minutes |
| With rationales | 1,500/min | ~80 minutes |

## Module Structure

```
gpt_5-2_soft_label/
├── __init__.py        # Package exports
├── __main__.py        # Entry point: python -m gpt_5-2_soft_label
├── config.py          # Rate limits, retry config, blob settings
├── client.py          # Azure OpenAI client + Key Vault
├── tokenizer.py       # tiktoken token ID resolution
├── prompts.py         # System prompts and templates
├── classifier.py      # Classification with logprobs + tenacity
├── rationale.py       # Rationale generation + tenacity
├── pipeline.py        # Async processing with semaphore
├── cli.py             # Command-line interface
├── README.md          # This documentation
│
├── io/                # Input/Output handling
│   ├── __init__.py
│   ├── blob_reader.py # Read RAW data from Azure Blob Storage
│   ├── blob_writer.py # Write LABELED data (safe, parallel folder)
│   └── schemas.py     # TurnRecord, LabeledTurnRecord, provenance
│
└── strategies/        # Labeling strategies
    ├── __init__.py
    ├── base.py        # Abstract strategy interface
    └── user_message_only.py  # Strategy A
```

## Installation

```bash
cd kusto_scripts/data_prep/llm_as_judge
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Label a Dataset (Rationales Enabled by Default)

```bash
python -m gpt_5-2_soft_label label \
    --input conversations.jsonl \
    --output labeled.jsonl \
    --model gpt-5.2
```

### Label Without Rationales (Faster, Cheaper)

```bash
python -m gpt_5-2_soft_label label \
    --input conversations.jsonl \
    --output labeled.jsonl \
    --model gpt-5.2 \
    --no-rationales
```

### Show Configuration

```bash
python -m gpt_5-2_soft_label info
```

### Test API Connectivity

```bash
python -m gpt_5-2_soft_label test \
    --message "How do I refactor this to use dependency injection?"
```

## Authentication

Priority order:
1. **Azure Key Vault** (production): Vault `abadawikeys`, Secret `gpt-5-2-api-key`
2. **Environment Variable** (development): `AZURE_OPENAI_API_KEY`

```bash
# Use Key Vault (default)
az login
python -m gpt_5-2_soft_label label ...

# Use env var only
export AZURE_OPENAI_API_KEY="your-key"
python -m gpt_5-2_soft_label label --no-keyvault ...
```

## Retry Logic (Tenacity)

All API calls use tenacity for robust retry:

| Setting | Value |
|---------|-------|
| Max retries | 5 |
| Min wait | 1 second |
| Max wait | 60 seconds |
| Backoff | Exponential (2x) |
| Retry on | 429, 500, 502, 503, 504 |

## Strategies

Strategies define **what the LLM sees** when classifying:

| Strategy | Description | Tokens |
|----------|-------------|--------|
| `user_message_only` | Just the user message, no context | Minimal |
| *(future)* `with_context` | Include previous turns | More |
| *(future)* `with_response` | Include model's response | More |

## Cost Estimation

| Mode | Tokens/turn | Cost @ $0.01/1k | 120k turns |
|------|-------------|-----------------|------------|
| Classification only | ~200 | $0.002 | $240 |
| With rationales | ~350 | $0.0035 | $420 |

## Troubleshooting

### "tiktoken not installed"
```bash
pip install tiktoken
```

### Rate limit errors
```bash
# Reduce concurrency
python -m gpt_5-2_soft_label label --concurrency 20 ...
```

### "No label in top_logprobs"
This is rare with logit_bias. Check:
- logit_bias is being applied
- Temperature is 1.0
- Model deployment supports logprobs
