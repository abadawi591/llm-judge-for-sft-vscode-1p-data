"""
Pipeline Module
===============

Dataset labeling pipeline with async concurrency control.

This module orchestrates the end-to-end labeling process:
    1. Read input data (from blob or local JSONL)
    2. Apply labeling strategy to extract text
    3. Classify with soft labels + rationales (default)
    4. Write minimal output (IDs + labels only)

Key Changes:
    - Rationales are now ENABLED BY DEFAULT
    - Uses tenacity for retry logic
    - Semaphore set to 50 concurrent (based on gpt-5.2 rate limits)
    - Output schema is minimal (IDs + labels only)

Concurrency Strategy:
    We use asyncio.Semaphore to limit concurrent API calls:
    - gpt-5.2 deployment: 10k requests/min, 1M tokens/min
    - With rationales: ~350 tokens/request
    - Token bottleneck: ~2,857 requests/min
    - Safe rate: ~1,000 requests/min (35% headroom)
    - Semaphore(50) with ~3s latency ≈ 1,000 requests/min
"""

import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from openai import AsyncAzureOpenAI

from .config import (
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    OUTPUT_FIELD_CONVERSATION_ID,
    OUTPUT_FIELD_MESSAGE_ID,
    OUTPUT_FIELD_HARD_LABEL,
    OUTPUT_FIELD_SOFT_LABEL,
    OUTPUT_FIELD_RATIONALE,
    OUTPUT_FIELD_ERROR,
)
from .tokenizer import get_label_token_ids, LabelTokenizer
from .classifier import classify_message
from .rationale import generate_rationale
from .io.schemas import TurnRecord, LabeledTurnRecord
from .strategies import get_strategy, LabelingStrategy

# Progress bar (optional)
try:
    from tqdm.asyncio import tqdm_asyncio
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


@dataclass
class LabelingStats:
    """
    Statistics from a labeling run.
    
    Attributes:
        total: Total turns processed
        success: Turns successfully labeled
        failed: Turns that failed labeling
        label_0_count: Count of label 0 (reasoning)
        label_1_count: Count of label 1 (non-reasoning)
        soft_label_sum: Sum of soft labels (for computing average)
        start_time: Pipeline start timestamp
        end_time: Pipeline end timestamp
    """
    total: int = 0
    success: int = 0
    failed: int = 0
    label_0_count: int = 0
    label_1_count: int = 0
    soft_label_sum: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    errors: list = field(default_factory=list)
    
    @property
    def avg_soft_label(self) -> float:
        """Average soft label (P(non-reasoning))."""
        return self.soft_label_sum / self.success if self.success > 0 else 0.0
    
    @property
    def duration_seconds(self) -> float:
        """Total pipeline duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    @property
    def turns_per_second(self) -> float:
        """Processing throughput."""
        return self.total / self.duration_seconds if self.duration_seconds > 0 else 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_turns": self.total,
            "success": self.success,
            "failed": self.failed,
            "label_0_count": self.label_0_count,
            "label_1_count": self.label_1_count,
            "avg_soft_label": round(self.avg_soft_label, 4),
            "duration_seconds": round(self.duration_seconds, 1),
            "turns_per_second": round(self.turns_per_second, 2),
            "error_count": len(self.errors),
        }
    
    def print_summary(self) -> None:
        """Print human-readable summary."""
        print("\n" + "=" * 60)
        print("LABELING PIPELINE SUMMARY")
        print("=" * 60)
        print(f"Total turns:       {self.total:,}")
        if self.total > 0:
            print(f"Successful:        {self.success:,} ({100*self.success/self.total:.1f}%)")
        print(f"Failed:            {self.failed:,}")
        print()
        print(f"Label 0 (reason):  {self.label_0_count:,}")
        print(f"Label 1 (simple):  {self.label_1_count:,}")
        print(f"Avg soft_label:    {self.avg_soft_label:.4f}")
        print()
        print(f"Duration:          {self.duration_seconds:.1f}s")
        print(f"Throughput:        {self.turns_per_second:.2f} turns/sec")
        print("=" * 60)


async def _process_single_turn(
    turn: TurnRecord,
    client: AsyncAzureOpenAI,
    model: str,
    tokenizer: LabelTokenizer,
    strategy: LabelingStrategy,
    with_rationales: bool,
    semaphore: asyncio.Semaphore,
    stats: LabelingStats,
) -> LabeledTurnRecord:
    """
    Process a single turn with semaphore-controlled concurrency.
    
    Args:
        turn: Input turn record
        client: Azure OpenAI client
        model: Deployment name
        tokenizer: Label tokenizer
        strategy: Labeling strategy to apply
        with_rationales: Whether to generate rationales
        semaphore: Concurrency control semaphore
        stats: Stats object to update
    
    Returns:
        LabeledTurnRecord with classification results
    """
    async with semaphore:
        try:
            # Apply strategy to get text to classify
            strategy_result = strategy.apply(turn)
            text_to_classify = strategy_result.text_to_classify
            
            if not text_to_classify:
                stats.failed += 1
                return LabeledTurnRecord.from_error(turn, "Empty user message")
            
            # Classify
            result = await classify_message(
                client=client,
                user_message=text_to_classify,
                model=model,
                tokenizer=tokenizer,
            )
            
            # Generate rationale (default: enabled)
            rationale = None
            if with_rationales:
                try:
                    rationale = await generate_rationale(
                        client=client,
                        user_message=text_to_classify,
                        model=model,
                        label=result.hard_label,
                    )
                except Exception as e:
                    rationale = f"[Error generating rationale: {str(e)[:100]}]"
            
            # Update stats
            stats.success += 1
            stats.soft_label_sum += result.soft_label
            if result.hard_label == 0:
                stats.label_0_count += 1
            else:
                stats.label_1_count += 1
            
            return LabeledTurnRecord.from_turn_and_result(
                turn=turn,
                hard_label=result.hard_label,
                soft_label=result.soft_label,
                rationale=rationale,
            )
            
        except Exception as e:
            stats.failed += 1
            stats.errors.append(str(e))
            return LabeledTurnRecord.from_error(turn, str(e))


async def label_turns(
    client: AsyncAzureOpenAI,
    turns: List[TurnRecord],
    model: str,
    strategy_name: str = "user_message_only",
    with_rationales: bool = True,  # DEFAULT: enabled
    concurrency: int = DEFAULT_CONCURRENCY,
) -> tuple:
    """
    Label a list of turns with soft labels and rationales.
    
    Args:
        client: AsyncAzureOpenAI client instance
        turns: List of TurnRecord objects to label
        model: Azure deployment name (e.g., "gpt-5.2")
        strategy_name: Name of labeling strategy (default: user_message_only)
        with_rationales: Generate rationales (default: True)
        concurrency: Maximum concurrent API calls (default: 50)
    
    Returns:
        Tuple of (List[LabeledTurnRecord], LabelingStats)
    
    Example:
        >>> results, stats = await label_turns(
        ...     client=client,
        ...     turns=turns,
        ...     model="gpt-5.2",
        ... )
        >>> stats.print_summary()
    """
    # Validate concurrency
    concurrency = min(max(1, concurrency), MAX_CONCURRENCY)
    
    # Initialize
    stats = LabelingStats()
    stats.total = len(turns)
    stats.start_time = datetime.now()
    
    # Get tokenizer
    print(f"Initializing tokenizer for model: {model}")
    tokenizer = get_label_token_ids(model=model)
    print(f"  Token '0' → ID {tokenizer.token_id_0}")
    print(f"  Token '1' → ID {tokenizer.token_id_1}")
    
    # Get strategy
    strategy = get_strategy(strategy_name)
    print(f"\nStrategy: {strategy.name}")
    print(f"  {strategy.description}")
    
    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(concurrency)
    
    print(f"\nLabeling {len(turns):,} turns...")
    print(f"  Concurrency: {concurrency}")
    print(f"  Rationales: {'enabled' if with_rationales else 'disabled'}")
    
    # Process turns
    tasks = [
        _process_single_turn(
            turn=turn,
            client=client,
            model=model,
            tokenizer=tokenizer,
            strategy=strategy,
            with_rationales=with_rationales,
            semaphore=semaphore,
            stats=stats,
        )
        for turn in turns
    ]
    
    # Execute with optional progress bar
    if TQDM_AVAILABLE:
        results = await tqdm_asyncio.gather(*tasks, desc="Labeling")
    else:
        print("  (Install tqdm for progress bars: pip install tqdm)")
        results = await asyncio.gather(*tasks)
    
    stats.end_time = datetime.now()
    
    return results, stats


async def label_dataset(
    client: AsyncAzureOpenAI,
    input_path: str,
    output_path: str,
    model: str,
    strategy_name: str = "user_message_only",
    with_rationales: bool = True,  # DEFAULT: enabled
    concurrency: int = DEFAULT_CONCURRENCY,
) -> LabelingStats:
    """
    Label a JSONL dataset and write minimal output.
    
    This function:
    1. Reads input JSONL (conversations with turns)
    2. Flattens to individual turns
    3. Labels each turn with soft labels + rationales
    4. Writes minimal output (IDs + labels only)
    
    Args:
        client: AsyncAzureOpenAI client instance
        input_path: Path to input JSONL file
        output_path: Path for output JSONL file
        model: Azure deployment name (e.g., "gpt-5.2")
        strategy_name: Name of labeling strategy
        with_rationales: Generate rationales (default: True)
        concurrency: Maximum concurrent API calls
    
    Returns:
        LabelingStats with run statistics
    
    Input Format (JSONL, one conversation per line):
        {"conversationId": "...", "turnsArray": [...], ...}
    
    Output Format (JSONL, one turn per line):
        {"conversationId": "...", "messageId": "...", "hard_label": 0, "soft_label": 0.23, "rationale": "..."}
    """
    from .io.schemas import ConversationRecord
    
    # Read input
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    print(f"Reading input: {input_path}")
    conversations = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                conv = ConversationRecord.from_dict(data)
                conversations.append(conv)
            except json.JSONDecodeError as e:
                print(f"  Warning: Skipping malformed line {line_num}: {e}")
    
    if not conversations:
        raise ValueError(f"No valid conversations in input file: {input_path}")
    
    print(f"  Loaded {len(conversations):,} conversations")
    
    # Flatten to turns
    turns = []
    for conv in conversations:
        turns.extend(conv.to_turn_records())
    
    print(f"  Flattened to {len(turns):,} turns")
    
    # Label turns
    results, stats = await label_turns(
        client=client,
        turns=turns,
        model=model,
        strategy_name=strategy_name,
        with_rationales=with_rationales,
        concurrency=concurrency,
    )
    
    # Write output
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"\nWriting output: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        for record in results:
            f.write(json.dumps(record.to_dict(), default=str) + '\n')
    
    stats.print_summary()
    
    return stats
