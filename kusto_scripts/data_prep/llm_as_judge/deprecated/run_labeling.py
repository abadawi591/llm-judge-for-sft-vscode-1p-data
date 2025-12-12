#!/usr/bin/env python3
"""
LLM-as-Judge Labeling Pipeline

Main entry point for running the reasoning classification labeling pipeline.
Supports both synchronous and asynchronous (parallel) execution with tenacity
retry logic for handling transient failures.

Usage:
    # Label with Strategy C (recommended), async by default
    python run_labeling.py --strategy C --input data.jsonl --output labels/
    
    # Force synchronous execution
    python run_labeling.py --strategy C --input data.jsonl --output labels/ --sync
    
    # Label with ensemble voting (A+B+C), async parallel
    python run_labeling.py --strategy ensemble --input data.jsonl --output labels/
    
    # Cascade mode (cost-efficient)
    python run_labeling.py --strategy cascade --input data.jsonl --output labels/
    
    # Test with small sample
    python run_labeling.py --strategy C --input data.jsonl --output labels/ --sample 100

Labels:
    0 = Reasoning Required
    1 = Non-Reasoning Sufficient

Azure Foundry Configuration:
    - Endpoint: https://pagolnar-5985-resource.services.ai.azure.com/anthropic/
    - Model: claude-sonnet-4-5
    - Key Vault: claude-keyvault / claude-sonnet-4-5-azurefoundary
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from tqdm import tqdm
from tqdm.asyncio import tqdm as tqdm_async

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from strategies.strategy_a.judge_strategy_a import StrategyAJudge
from strategies.strategy_b.judge_strategy_b import StrategyBJudge
from strategies.strategy_c.judge_strategy_c import StrategyCJudge
from voting.ensemble import EnsembleJudge, CascadeJudge
from config.azure_foundry import ASYNC_AVAILABLE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Loading
# =============================================================================

def load_jsonl(filepath: str, sample: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load records from a JSONL file."""
    records = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
                if sample and len(records) >= sample:
                    break
    logger.info(f"Loaded {len(records)} records from {filepath}")
    return records


def save_jsonl(records: List[Dict[str, Any]], filepath: str):
    """Save records to a JSONL file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
    logger.info(f"Saved {len(records)} records to {filepath}")


# =============================================================================
# Synchronous Labeling Functions
# =============================================================================

def label_with_strategy_a_sync(records: List[Dict[str, Any]], include_raw: bool = False) -> List[Dict[str, Any]]:
    """Label records using Strategy A (sync)."""
    judge = StrategyAJudge()
    results = []
    
    for record in tqdm(records, desc="Strategy A (sync)"):
        result = judge.classify(record.get("userMessage", ""), include_raw=include_raw)
        
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "A",
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        if result.error:
            labeled["error"] = result.error
        
        results.append(labeled)
    
    return results


def label_with_strategy_b_sync(records: List[Dict[str, Any]], include_raw: bool = False) -> List[Dict[str, Any]]:
    """Label records using Strategy B (sync)."""
    judge = StrategyBJudge()
    results = []
    
    for record in tqdm(records, desc="Strategy B (sync)"):
        result = judge.classify_from_record(record, include_raw=include_raw)
        
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "B",
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        if result.error:
            labeled["error"] = result.error
        
        results.append(labeled)
    
    return results


def label_with_strategy_c_sync(records: List[Dict[str, Any]], include_raw: bool = False) -> List[Dict[str, Any]]:
    """Label records using Strategy C (sync)."""
    judge = StrategyCJudge()
    results = []
    
    for record in tqdm(records, desc="Strategy C (sync)"):
        turns = record.get("turnsArray", [])
        turn_index = record.get("turnIndex", len(turns) - 1)
        
        result = judge.classify_turn(
            turns=turns,
            turn_index=turn_index,
            conversation_id=record.get("conversationId"),
            include_raw=include_raw
        )
        
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "C",
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        if result.error:
            labeled["error"] = result.error
        
        results.append(labeled)
    
    return results


def label_with_ensemble_sync(records: List[Dict[str, Any]], include_raw: bool = False) -> List[Dict[str, Any]]:
    """Label records using ensemble voting (sync)."""
    judge = EnsembleJudge(strategies=["A", "B", "C"])
    results = []
    
    for record in tqdm(records, desc="Ensemble (sync)"):
        result = judge.classify(record, include_raw=include_raw)
        
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "ensemble",
            "agreement": result.agreement,
            "agreement_ratio": result.agreement_ratio,
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        
        results.append(labeled)
    
    return results


def label_with_cascade_sync(records: List[Dict[str, Any]], include_raw: bool = False) -> List[Dict[str, Any]]:
    """Label records using cascade voting (sync)."""
    judge = CascadeJudge()
    results = []
    
    for record in tqdm(records, desc="Cascade (sync)"):
        result = judge.classify(record, include_raw=include_raw)
        
        labeled = {
            **record,
            **result,
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        
        results.append(labeled)
    
    return results


# =============================================================================
# Asynchronous Labeling Functions
# =============================================================================

async def label_with_strategy_a_async(
    records: List[Dict[str, Any]],
    include_raw: bool = False,
    max_concurrency: int = 10
) -> List[Dict[str, Any]]:
    """Label records using Strategy A (async, parallel)."""
    judge = StrategyAJudge(max_concurrency=max_concurrency)
    
    messages = [r.get("userMessage", "") for r in records]
    classification_results = await judge.classify_batch_async(messages, include_raw=include_raw)
    
    results = []
    for record, result in zip(records, classification_results):
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "A",
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        if result.error:
            labeled["error"] = result.error
        results.append(labeled)
    
    return results


async def label_with_strategy_b_async(
    records: List[Dict[str, Any]],
    include_raw: bool = False,
    max_concurrency: int = 10
) -> List[Dict[str, Any]]:
    """Label records using Strategy B (async, parallel)."""
    judge = StrategyBJudge(max_concurrency=max_concurrency)
    
    classification_results = await judge.classify_batch_async(records, include_raw=include_raw)
    
    results = []
    for record, result in zip(records, classification_results):
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "B",
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        if result.error:
            labeled["error"] = result.error
        results.append(labeled)
    
    return results


async def label_with_strategy_c_async(
    records: List[Dict[str, Any]],
    include_raw: bool = False,
    max_concurrency: int = 10
) -> List[Dict[str, Any]]:
    """Label records using Strategy C (async, parallel)."""
    judge = StrategyCJudge(max_concurrency=max_concurrency)
    
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def process_record(record: Dict, idx: int) -> tuple[int, Dict]:
        async with semaphore:
            turns = record.get("turnsArray", [])
            turn_index = record.get("turnIndex", len(turns) - 1)
            
            result = await judge.classify_turn_async(
                turns=turns,
                turn_index=turn_index,
                conversation_id=record.get("conversationId"),
                include_raw=include_raw
            )
            
            labeled = {
                **record,
                "label": result.label,
                "confidence": result.confidence,
                "strategy": "C",
                "labeled_at": datetime.utcnow().isoformat() + "Z"
            }
            if result.error:
                labeled["error"] = result.error
            
            return idx, labeled
    
    tasks = [process_record(r, i) for i, r in enumerate(records)]
    results_with_idx = await tqdm_async.gather(*tasks, desc="Strategy C (async)")
    results_with_idx.sort(key=lambda x: x[0])
    
    return [r for _, r in results_with_idx]


async def label_with_ensemble_async(
    records: List[Dict[str, Any]],
    include_raw: bool = False,
    max_concurrency: int = 10
) -> List[Dict[str, Any]]:
    """Label records using ensemble voting (async, parallel)."""
    judge = EnsembleJudge(strategies=["A", "B", "C"])
    
    classification_results = await judge.classify_batch_async(
        records, include_raw=include_raw, max_concurrency=max_concurrency
    )
    
    results = []
    for record, result in zip(records, classification_results):
        labeled = {
            **record,
            "label": result.label,
            "confidence": result.confidence,
            "strategy": "ensemble",
            "agreement": result.agreement,
            "agreement_ratio": result.agreement_ratio,
            "labeled_at": datetime.utcnow().isoformat() + "Z"
        }
        results.append(labeled)
    
    return results


async def label_with_cascade_async(
    records: List[Dict[str, Any]],
    include_raw: bool = False,
    max_concurrency: int = 10
) -> List[Dict[str, Any]]:
    """Label records using cascade voting (async, parallel)."""
    judge = CascadeJudge()
    
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def process_record(record: Dict, idx: int) -> tuple[int, Dict]:
        async with semaphore:
            result = await judge.classify_async(record, include_raw=include_raw)
            labeled = {
                **record,
                **result,
                "labeled_at": datetime.utcnow().isoformat() + "Z"
            }
            return idx, labeled
    
    tasks = [process_record(r, i) for i, r in enumerate(records)]
    results_with_idx = await tqdm_async.gather(*tasks, desc="Cascade (async)")
    results_with_idx.sort(key=lambda x: x[0])
    
    return [r for _, r in results_with_idx]


# =============================================================================
# Statistics
# =============================================================================

def print_statistics(results: List[Dict[str, Any]], elapsed_time: float):
    """Print labeling statistics."""
    total = len(results)
    reasoning = sum(1 for r in results if r.get("label") == 0)
    non_reasoning = sum(1 for r in results if r.get("label") == 1)
    errors = sum(1 for r in results if r.get("label", -1) < 0)
    
    avg_confidence = sum(r.get("confidence", 0) for r in results) / max(total, 1)
    high_conf = sum(1 for r in results if r.get("confidence", 0) >= 0.85)
    low_conf = sum(1 for r in results if 0 < r.get("confidence", 0) < 0.70)
    
    print("\n" + "=" * 60)
    print("LABELING STATISTICS")
    print("=" * 60)
    print(f"Total records:     {total:,}")
    print(f"  Reasoning (0):   {reasoning:,} ({reasoning/total*100:.1f}%)")
    print(f"  Non-reason (1):  {non_reasoning:,} ({non_reasoning/total*100:.1f}%)")
    print(f"  Errors:          {errors:,} ({errors/total*100:.1f}%)")
    print(f"\nConfidence:")
    print(f"  Average:         {avg_confidence:.2f}")
    print(f"  High (≥0.85):    {high_conf:,} ({high_conf/total*100:.1f}%)")
    print(f"  Low (<0.70):     {low_conf:,} ({low_conf/total*100:.1f}%)")
    print(f"\nPerformance:")
    print(f"  Elapsed time:    {elapsed_time:.1f}s")
    print(f"  Throughput:      {total/elapsed_time:.1f} records/s")
    print("=" * 60)


# =============================================================================
# Main
# =============================================================================

async def async_main(args):
    """Async main function."""
    # Load data
    logger.info(f"Loading data from {args.input}")
    records = load_jsonl(args.input, sample=args.sample)
    
    if not records:
        logger.error("No records to process")
        return 1
    
    # Run labeling
    logger.info(f"Labeling {len(records)} records with strategy: {args.strategy} (async)")
    start_time = time.time()
    
    if args.strategy == "A":
        results = await label_with_strategy_a_async(records, args.include_raw, args.concurrency)
    elif args.strategy == "B":
        results = await label_with_strategy_b_async(records, args.include_raw, args.concurrency)
    elif args.strategy == "C":
        results = await label_with_strategy_c_async(records, args.include_raw, args.concurrency)
    elif args.strategy == "ensemble":
        results = await label_with_ensemble_async(records, args.include_raw, args.concurrency)
    elif args.strategy == "cascade":
        results = await label_with_cascade_async(records, args.include_raw, args.concurrency)
    
    elapsed_time = time.time() - start_time
    
    # Save output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(args.output) / f"labeled_{args.strategy}_{timestamp}.jsonl"
    save_jsonl(results, str(output_file))
    
    # Print statistics
    if not args.no_stats:
        print_statistics(results, elapsed_time)
    
    logger.info(f"Done! Output saved to {output_file}")
    return 0


def sync_main(args):
    """Sync main function."""
    # Load data
    logger.info(f"Loading data from {args.input}")
    records = load_jsonl(args.input, sample=args.sample)
    
    if not records:
        logger.error("No records to process")
        return 1
    
    # Run labeling
    logger.info(f"Labeling {len(records)} records with strategy: {args.strategy} (sync)")
    start_time = time.time()
    
    if args.strategy == "A":
        results = label_with_strategy_a_sync(records, args.include_raw)
    elif args.strategy == "B":
        results = label_with_strategy_b_sync(records, args.include_raw)
    elif args.strategy == "C":
        results = label_with_strategy_c_sync(records, args.include_raw)
    elif args.strategy == "ensemble":
        results = label_with_ensemble_sync(records, args.include_raw)
    elif args.strategy == "cascade":
        results = label_with_cascade_sync(records, args.include_raw)
    
    elapsed_time = time.time() - start_time
    
    # Save output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(args.output) / f"labeled_{args.strategy}_{timestamp}.jsonl"
    save_jsonl(results, str(output_file))
    
    # Print statistics
    if not args.no_stats:
        print_statistics(results, elapsed_time)
    
    logger.info(f"Done! Output saved to {output_file}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="LLM-as-Judge Labeling Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Async (default, faster)
  python run_labeling.py --strategy C --input data.jsonl --output labels/
  
  # Sync (sequential)
  python run_labeling.py --strategy C --input data.jsonl --output labels/ --sync
  
  # Ensemble voting
  python run_labeling.py --strategy ensemble --input data.jsonl --output labels/
        """
    )
    
    parser.add_argument(
        "--strategy", "-s",
        choices=["A", "B", "C", "ensemble", "cascade"],
        default="C",
        help="Labeling strategy to use (default: C)"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input JSONL file with records to label"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/",
        help="Output directory for labeled data (default: output/)"
    )
    parser.add_argument(
        "--sample",
        type=int,
        help="Only process first N records (for testing)"
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw LLM responses in output"
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Don't print statistics after labeling"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Use synchronous (sequential) execution instead of async"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Maximum concurrent requests for async mode (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Check async availability
    if not args.sync and not ASYNC_AVAILABLE:
        logger.warning("Async not available, falling back to sync mode")
        args.sync = True
    
    # Run
    if args.sync:
        return sync_main(args)
    else:
        return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
