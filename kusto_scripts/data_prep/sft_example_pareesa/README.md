# SFT Example Data - Pareesa's Pipeline

## Overview

This folder contains example data from a colleague's (Pareesa) SFT data curation pipeline for training a reasoning vs non-reasoning classifier.

## Files

| File | Description | Size |
|------|-------------|------|
| `part-00000-tid-...json` | Raw curated conversation data from telemetry | ~200MB |
| `datav3_train_70r_30n_sft.jsonl` | Final SFT-formatted training data | Smaller |

## Pipeline Summary

### Step 1: Raw Data Curation

Raw conversation data was extracted from GitHub Copilot telemetry containing:

```json
{
  "Name": "GitHub.copilot-chat/interactiveSessionResponse",
  "request": "user's original message",
  "response": "model's full response",
  "llm_vote": 0,           // LLM judge annotation (0=reasoning, 1=non-reasoning)
  "vote": 1,               // Human vote (thumbs up/down)
  "model": "gpt-5",
  "latency": 408,
  "turnNumber": 1,
  "userName": "...",
  ...
}
```

### Step 2: LLM Judge Annotation

An LLM judge was used to classify each user request:

**Input to LLM Judge:**
- The user's `request` (message text only)

**Task:**
- Determine if the request requires a reasoning-capable model (0) or if a non-reasoning model is sufficient (1)

**Output:**
- Binary label stored in `llm_vote` field

### Step 3: SFT Format Conversion

The annotated data was converted to OpenAI's fine-tuning format:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Assess whether the user request requires a reasoning-capable LLM.\n\tOutput 1 if a non-reasoning model is sufficient.\n\tOutput 0 if a reasoning model is required.\n\tRespond with a single digit: 0 or 1."
    },
    {
      "role": "user", 
      "content": "<original user request from conversation>"
    },
    {
      "role": "assistant",
      "content": "0 or 1"
    }
  ]
}
```

## Naming Convention

`datav3_train_70r_30n_sft.jsonl`:
- `datav3`: Version 3 of the dataset
- `train`: Training split
- `70r_30n`: 70% reasoning (label=0), 30% non-reasoning (label=1)
- `sft`: Supervised Fine-Tuning format

## Key Design Decisions

1. **Minimal Input**: Only the user request was shown to the LLM judge (not the full conversation or model response)
2. **Binary Classification**: Simple 0/1 output for ease of training
3. **System Prompt**: Clear instructions defining the classification task
4. **Balanced Dataset**: Approximate 70/30 split between classes

## Usage

This SFT data can be used to fine-tune a smaller model to:
- Route requests to appropriate models (reasoning vs fast/cheap)
- Predict computational requirements before processing
- Optimize model selection in production

## Related Work

See the `raw_data_curation_databricks/` folder for our expanded data curation pipeline that includes:
- Multi-turn conversation context
- Token usage metrics
- Tool call information
- Turn duration and latency data

