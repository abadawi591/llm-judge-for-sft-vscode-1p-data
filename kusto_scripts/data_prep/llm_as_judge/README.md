# LLM-as-Judge: Reasoning Classification System

> **Goal:** Automatically label ~120k curated Copilot Agent Mode conversations to classify whether a request requires a reasoning-capable LLM.

## Features

- ✅ **Async API calls** - Parallel processing for 5-10x speedup
- ✅ **Tenacity retry logic** - Automatic retries with exponential backoff
- ✅ **Multiple strategies** - A, B, C with different input contexts
- ✅ **Ensemble voting** - Combine strategies for higher accuracy
- ✅ **Cascade mode** - Cost-efficient escalation based on confidence

## Labels

| Label | Meaning | Example |
|-------|---------|---------|
| `0` | **Reasoning Required** | Complex multi-step debugging, architectural decisions |
| `1` | **Non-Reasoning Sufficient** | Simple lookups, direct questions, straightforward edits |

---

## Folder Structure

```
llm_as_judge/
├── README.md                    # This file
├── config/
│   ├── azure_foundry.py         # Azure Foundry client setup
│   └── settings.py              # Configuration settings
├── strategies/
│   ├── strategy_a/              # Text-Only (Baseline)
│   │   ├── STRATEGY_A.md        # Detailed documentation
│   │   └── judge_strategy_a.py  # Implementation
│   ├── strategy_b/              # Text + Behavioral Metrics
│   │   ├── STRATEGY_B.md        # Detailed documentation
│   │   └── judge_strategy_b.py  # Implementation
│   └── strategy_c/              # Text + Conversation History
│       ├── STRATEGY_C.md        # Detailed documentation
│       └── judge_strategy_c.py  # Implementation
├── voting/
│   ├── VOTING_STRATEGIES.md     # Multi-judge voting approaches
│   └── ensemble.py              # Voting implementation
└── run_labeling.py              # Main entry point
```

---

## Strategy Comparison

| Strategy | Input | Cost/Call | Accuracy | Deployment Ready |
|----------|-------|-----------|----------|------------------|
| **A: Text Only** | User message | ~$0.001 | Baseline | ✅ Yes |
| **B: Text + Metrics** | User message + telemetry | ~$0.002 | Good | ❌ No (uses hindsight) |
| **C: Text + History** | User message + last N turns | ~$0.005 | Best | ✅ Yes |

---

## LLM Judge Configuration

### Model: Claude Sonnet 4.5 on Azure Foundry

```python
Endpoint:  https://pagolnar-5985-resource.services.ai.azure.com/anthropic/
Model:     claude-sonnet-4-5 (version 20250929)
Key Vault: claude-keyvault
Secret:    claude-sonnet-4-5-azurefoundary
```

### Rate Limits
- **Tokens per minute:** 150,000
- **Requests per minute:** 150

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Login to Azure
az login

# 3. Run labeling with Strategy C (recommended, async by default)
python run_labeling.py --strategy C --input data/conversations.jsonl --output labels/

# 4. Or run synchronously
python run_labeling.py --strategy C --input data/conversations.jsonl --output labels/ --sync

# 5. Ensemble voting (parallel across strategies)
python run_labeling.py --strategy ensemble --input data.jsonl --output labels/

# 6. Adjust concurrency (default: 10)
python run_labeling.py --strategy C --input data.jsonl --output labels/ --concurrency 20
```

## Async vs Sync Performance

| Mode | 1000 records | Speedup |
|------|--------------|---------|
| Sync (sequential) | ~30 min | 1x |
| Async (10 concurrent) | ~3 min | **10x** |
| Async (20 concurrent) | ~2 min | **15x** |

⚠️ **Rate limits:** Azure Foundry allows 150 requests/min. Adjust `--concurrency` accordingly.

---

## Retry Logic (Tenacity)

All API calls are wrapped with tenacity for automatic retry:

```python
# Configuration
MAX_RETRIES = 5
MIN_WAIT = 1 second
MAX_WAIT = 60 seconds
BACKOFF = exponential
```

Handles:
- Rate limiting (429)
- Network timeouts
- Transient server errors (5xx)

---

## Output Format

Each labeled record includes:

```json
{
  "conversationId": "abc-123",
  "turnIndex": 5,
  "userMessage": "Fix the authentication bug",
  "label": 0,
  "confidence": 0.92,
  "strategy": "C",
  "labeled_at": "2025-12-10T08:30:00Z"
}
```

---

## Recommendations

1. **Primary labeling:** Use **Strategy C** for best accuracy
2. **Voting:** Combine A, B, C votes for ambiguous cases
3. **Gold standard:** Use full context (Strategy D in voting) for 10% eval set
4. **Validation:** Human review 5% of labels

---

## Cost Estimates

| Dataset | Turns | Strategy | Estimated Cost |
|---------|-------|----------|----------------|
| 120k convos | ~600k turns | A only | ~$100 |
| 120k convos | ~600k turns | C only | ~$500 |
| 120k convos | ~600k turns | A+B+C voting | ~$800 |

---

## Related Documentation

- [Strategy A Details](strategies/strategy_a/STRATEGY_A.md)
- [Strategy B Details](strategies/strategy_b/STRATEGY_B.md)
- [Strategy C Details](strategies/strategy_c/STRATEGY_C.md)
- [Voting Strategies](voting/VOTING_STRATEGIES.md)

